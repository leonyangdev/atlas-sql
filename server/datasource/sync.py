"""元数据同步服务：把 inspector 采集结果幂等写入控制库。

增量同步规则：
- 已存在的表/列：只更新从源库采集的字段（raw_comment, row_estimate, data_type 等），
  ``manual_*`` 字段保持不变，确保人工注释不被覆盖。
- 新增的表/列：完整插入，manual_* 字段为 NULL 等待人工补充。
- 源库已删除的表/列：设置 is_deleted=True，不物理删除，保留人工注释。

整个同步在 MetadataSyncJob 记录中追踪状态，支持断点重试（Celery 在 V0-S04-T04 中接入）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import asyncpg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.datasource.inspector import TableInfo, collect_tables, serialize_sample_values
from server.datasource.models import (
    ColumnMetadata,
    DataSource,
    MetadataSyncJob,
    SyncStatus,
    TableMetadata,
)

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """同步过程中可以安全对外报告的错误；不含连接串或密码。"""


async def run_metadata_sync(
    session: AsyncSession,
    datasource: DataSource,
    job: MetadataSyncJob,
    source_url: str,
    schema_name: str = "public",
) -> None:
    """执行一次完整的元数据同步，更新 job 状态。

    Args:
        session: 控制库 ORM 会话（调用方负责 commit/rollback）。
        datasource: 已从控制库加载的数据源实体。
        job: 当前同步任务记录，函数会直接修改其状态字段。
        source_url: 实际连接串（调用方已从 credential_ref 解析），不能传入控制库 URL。
        schema_name: 被采集的目标 schema，默认 public。
    """
    # 标记任务为运行中
    job.status = SyncStatus.RUNNING
    job.started_at = datetime.now(UTC)
    await session.flush()

    try:
        # 从源库采集元数据
        tables = await _collect_from_source(source_url, schema_name)

        # 将采集结果幂等写入控制库
        tables_count, columns_count = await _upsert_metadata(
            session, datasource.id, tables, schema_name
        )

        # 标记已消失对象
        known_tables = {t.table_name for t in tables}
        await _mark_deleted_tables(session, datasource.id, schema_name, known_tables)

        job.status = SyncStatus.SUCCEEDED
        job.tables_discovered = tables_count
        job.columns_discovered = columns_count
        job.finished_at = datetime.now(UTC)
        logger.info(
            "metadata sync succeeded datasource=%s tables=%d columns=%d",
            datasource.slug,
            tables_count,
            columns_count,
        )

    except SyncError as exc:
        job.status = SyncStatus.FAILED
        job.error_summary = str(exc)
        job.finished_at = datetime.now(UTC)
        logger.warning("metadata sync failed datasource=%s error=%s", datasource.slug, exc)
        raise
    except Exception as exc:
        # 捕获未预期的异常，转为 SyncError 以防止连接串等敏感信息进入日志
        safe_msg = f"{type(exc).__name__}: connection or query error"
        job.status = SyncStatus.FAILED
        job.error_summary = safe_msg
        job.finished_at = datetime.now(UTC)
        logger.exception("unexpected sync error datasource=%s", datasource.slug)
        raise SyncError(safe_msg) from exc


async def _collect_from_source(source_url: str, schema_name: str) -> list[TableInfo]:
    """连接源库并采集元数据，连接始终在 finally 中关闭。"""
    dsn = source_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(dsn=dsn, timeout=30)
    except (asyncpg.InvalidAuthorizationSpecificationError, OSError) as exc:
        # 故意丢弃 exc 内容，避免连接串或密码泄露到上层
        raise SyncError("cannot connect to source database") from exc
    try:
        return await collect_tables(conn, schema_name=schema_name)
    except asyncpg.PostgresError as exc:
        raise SyncError(f"query error during metadata collection: {type(exc).__name__}") from exc
    finally:
        await conn.close()


async def _upsert_metadata(
    session: AsyncSession,
    datasource_id: int,
    tables: list[TableInfo],
    schema_name: str,
) -> tuple[int, int]:
    """幂等地插入或更新表和列元数据，返回 (表数, 列数)。"""
    now = datetime.now(UTC)
    total_columns = 0

    for table_info in tables:
        # 查找已存在记录
        result = await session.execute(
            select(TableMetadata).where(
                TableMetadata.datasource_id == datasource_id,
                TableMetadata.schema_name == schema_name,
                TableMetadata.table_name == table_info.table_name,
            )
        )
        table_meta = result.scalar_one_or_none()

        if table_meta is None:
            # 新增：完整插入
            table_meta = TableMetadata(
                datasource_id=datasource_id,
                schema_name=schema_name,
                table_name=table_info.table_name,
                table_type=table_info.table_type,
                row_estimate=table_info.row_estimate,
                raw_comment=table_info.raw_comment,
                is_deleted=False,
                synced_at=now,
            )
            session.add(table_meta)
            await session.flush()  # 获取 table_meta.id
        else:
            # 更新：只改采集字段，不覆盖 manual_* 字段
            table_meta.table_type = table_info.table_type
            table_meta.row_estimate = table_info.row_estimate
            table_meta.raw_comment = table_info.raw_comment
            table_meta.is_deleted = False
            table_meta.synced_at = now

        # 处理列
        known_column_names = {col.column_name for col in table_info.columns}
        total_columns += len(table_info.columns)

        for col_info in table_info.columns:
            col_result = await session.execute(
                select(ColumnMetadata).where(
                    ColumnMetadata.table_id == table_meta.id,
                    ColumnMetadata.column_name == col_info.column_name,
                )
            )
            col_meta = col_result.scalar_one_or_none()
            sample_json = (
                serialize_sample_values(col_info.sample_values) if col_info.sample_values else None
            )

            if col_meta is None:
                col_meta = ColumnMetadata(
                    table_id=table_meta.id,
                    column_name=col_info.column_name,
                    ordinal_position=col_info.ordinal_position,
                    data_type=col_info.data_type,
                    character_maximum_length=col_info.character_maximum_length,
                    numeric_precision=col_info.numeric_precision,
                    numeric_scale=col_info.numeric_scale,
                    is_nullable=col_info.is_nullable,
                    column_default=col_info.column_default,
                    is_primary_key=col_info.is_primary_key,
                    foreign_key_ref=col_info.foreign_key_ref,
                    raw_comment=col_info.raw_comment,
                    sample_values=sample_json,
                    is_deleted=False,
                    synced_at=now,
                )
                session.add(col_meta)
            else:
                # 只更新采集字段，保留 manual_* 字段
                col_meta.ordinal_position = col_info.ordinal_position
                col_meta.data_type = col_info.data_type
                col_meta.character_maximum_length = col_info.character_maximum_length
                col_meta.numeric_precision = col_info.numeric_precision
                col_meta.numeric_scale = col_info.numeric_scale
                col_meta.is_nullable = col_info.is_nullable
                col_meta.column_default = col_info.column_default
                col_meta.is_primary_key = col_info.is_primary_key
                col_meta.foreign_key_ref = col_info.foreign_key_ref
                col_meta.raw_comment = col_info.raw_comment
                col_meta.sample_values = sample_json
                col_meta.is_deleted = False
                col_meta.synced_at = now

        # 标记该表中已消失的列
        await _mark_deleted_columns(session, table_meta.id, known_column_names)

    return len(tables), total_columns


async def _mark_deleted_tables(
    session: AsyncSession,
    datasource_id: int,
    schema_name: str,
    known_tables: set[str],
) -> None:
    """把控制库中有记录但本次未采集到的表标记为已删除。"""
    result = await session.execute(
        select(TableMetadata).where(
            TableMetadata.datasource_id == datasource_id,
            TableMetadata.schema_name == schema_name,
            TableMetadata.is_deleted.is_(False),
        )
    )
    for table_meta in result.scalars():
        if table_meta.table_name not in known_tables:
            table_meta.is_deleted = True
            logger.info(
                "table marked as deleted datasource_id=%d table=%s",
                datasource_id,
                table_meta.table_name,
            )


async def _mark_deleted_columns(
    session: AsyncSession,
    table_id: int,
    known_columns: set[str],
) -> None:
    """把该表中已消失的列标记为已删除。"""
    result = await session.execute(
        select(ColumnMetadata).where(
            ColumnMetadata.table_id == table_id,
            ColumnMetadata.is_deleted.is_(False),
        )
    )
    for col_meta in result.scalars():
        if col_meta.column_name not in known_columns:
            col_meta.is_deleted = True
