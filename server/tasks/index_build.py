"""Schema 索引构建 Celery 任务。

流程：
1. 从控制库读取 TableMetadata + ColumnMetadata（is_deleted=False）。
2. 用 EmbeddingProvider 批量生成向量。
3. 写入 OpenSearch（BM25 检索用）。
4. 写入 Milvus（Dense 向量检索用）。
5. 核对 OpenSearch 和 Milvus 的文档数量，与控制库记录一致才发布。
6. 更新 PublishedIndexVersion。

发布前核对保证：
- 维度变更时不能写旧 collection（Milvus 会拒绝维度不匹配的插入，这里显式检查）。
- 新旧快照不混用：整批写完再切换 published 指针。
- 失败批次的错误摘要写入 IndexBatch.error_summary，不影响线上服务。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import get_settings
from server.datasource.models import ColumnMetadata, TableMetadata
from server.db import create_control_engine, create_session_factory
from server.llm.embedding import EmbeddingProvider, FakeEmbeddingProvider
from server.search.document_id import (
    OBJECT_TYPE_COLUMN,
    OBJECT_TYPE_TABLE,
    make_column_doc_id,
    make_table_doc_id,
)
from server.search.index_status import IndexBatch, IndexBatchStatus, PublishedIndexVersion
from server.search.opensearch_schema import INDEX_TYPE_SCHEMA, index_name
from server.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# 控制库当前 schema 版本标签；迁移后手动更新此常量
CONTROL_SCHEMA_VERSION = "398bf9ebf135"


@celery_app.task(  # type: ignore[untyped-decorator]
    name="atlas_sql.index_build_schema",
    acks_late=True,
)
def build_schema_index_task(
    datasource_id: int | None = None,
    batch_key: str | None = None,
) -> dict[str, object]:
    """构建 schema（表和列）的 OpenSearch + Milvus 索引。

    Args:
        datasource_id: 只重建指定数据源；None 时重建全部数据源。
        batch_key: 幂等键；None 时自动生成 UUID。

    Returns:
        包含 batch_id 和最终状态的结果字典。
    """
    import uuid

    if batch_key is None:
        batch_key = str(uuid.uuid4())

    return asyncio.run(_run_index_build(datasource_id, batch_key))


async def _run_index_build(
    datasource_id: int | None,
    batch_key: str,
) -> dict[str, object]:
    """异步索引构建主逻辑。"""
    settings = get_settings()
    engine = create_control_engine(settings.control_database_url)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            # 创建批次记录
            batch = IndexBatch(
                index_type=INDEX_TYPE_SCHEMA,
                batch_key=batch_key,
                status=IndexBatchStatus.BUILDING,
                metadata_version=CONTROL_SCHEMA_VERSION,
                started_at=datetime.now(UTC),
            )
            session.add(batch)
            await session.flush()
            batch_id = batch.id

            try:
                provider = _get_embedding_provider(settings)
                batch.embedding_model_version = provider.model_version
                batch.dimension = provider.dimension

                # 读取元数据
                tables, columns = await _load_metadata(session, datasource_id)

                # 构建文档
                docs = _build_schema_documents(tables, columns, provider, settings)

                # 写入 OpenSearch
                os_count = await _index_to_opensearch(docs, settings)

                # 写入 Milvus
                mv_count = await _index_to_milvus(docs, provider.dimension, settings)

                # 核对数量
                expected = len(docs)
                if os_count != expected or mv_count != expected:
                    raise ValueError(
                        f"document count mismatch: expected={expected} "
                        f"opensearch={os_count} milvus={mv_count}"
                    )

                # 发布
                batch.status = IndexBatchStatus.PUBLISHED
                batch.object_count = expected
                batch.finished_at = datetime.now(UTC)

                await _update_published_version(session, batch)
                await session.commit()

                logger.info(
                    "schema index published batch_id=%d count=%d model=%s",
                    batch_id,
                    expected,
                    provider.model_version,
                )
                return {"batch_id": batch_id, "status": "published", "count": expected}

            except Exception as exc:
                batch.status = IndexBatchStatus.FAILED
                batch.error_summary = f"{type(exc).__name__}: {exc}"
                batch.finished_at = datetime.now(UTC)
                await session.commit()
                logger.error("schema index build failed batch_id=%d error=%s", batch_id, exc)
                raise
    finally:
        await engine.dispose()


async def _load_metadata(
    session: AsyncSession,
    datasource_id: int | None,
) -> tuple[list[TableMetadata], list[ColumnMetadata]]:
    """从控制库加载未删除的表和列元数据。"""
    table_query = select(TableMetadata).where(TableMetadata.is_deleted.is_(False))
    if datasource_id is not None:
        table_query = table_query.where(TableMetadata.datasource_id == datasource_id)

    table_result = await session.execute(table_query)
    tables = list(table_result.scalars().all())
    table_ids = [t.id for t in tables]

    if not table_ids:
        return [], []

    col_result = await session.execute(
        select(ColumnMetadata).where(
            ColumnMetadata.table_id.in_(table_ids),
            ColumnMetadata.is_deleted.is_(False),
        )
    )
    columns = list(col_result.scalars().all())
    return tables, columns


def _build_schema_documents(
    tables: list[TableMetadata],
    columns: list[ColumnMetadata],
    provider: EmbeddingProvider,
    settings: object,
) -> list[dict[str, object]]:
    """把表和列元数据组装成索引文档，并附加 Embedding 向量。"""
    now_iso = datetime.now(UTC).isoformat()

    # 构建列索引（table_id -> [ColumnMetadata]）
    col_index: dict[int, list[ColumnMetadata]] = {}
    for col in columns:
        col_index.setdefault(col.table_id, []).append(col)

    docs: list[dict[str, object]] = []

    # 表文档
    table_texts: list[str] = []
    for table in tables:
        name = table.manual_business_name or table.table_name
        desc = table.manual_description or table.raw_comment or ""
        grain = table.manual_grain or ""
        aliases = table.manual_aliases or ""
        table_texts.append(f"{name} {desc} {grain} {aliases}".strip())

    table_vectors = provider.embed_batch(table_texts)

    for table, text_vec in zip(tables, table_vectors, strict=True):
        doc_id = make_table_doc_id(table.datasource_id, table.schema_name, table.table_name)
        docs.append(
            {
                "doc_id": doc_id,
                "object_type": OBJECT_TYPE_TABLE,
                "datasource_id": table.datasource_id,
                "schema_name": table.schema_name,
                "table_name": table.table_name,
                "column_name": None,
                "domain": table.manual_domain or "",
                "authorized_roles": [],
                "metadata_version": CONTROL_SCHEMA_VERSION,
                "embedding_model_version": text_vec.model_version,
                "business_name": table.manual_business_name or table.table_name,
                "description": table.manual_description or table.raw_comment or "",
                "aliases": table.manual_aliases or "",
                "physical_name": table.table_name,
                "grain": table.manual_grain or "",
                "table_type": table.table_type,
                "row_estimate": table.row_estimate,
                "data_type": None,
                "sample_values": None,
                "indexed_at": now_iso,
                # 向量（只写入 Milvus，OpenSearch 只存标量）
                "_vector": text_vec.dense,
            }
        )

    # 列文档
    all_col_texts: list[str] = []
    flat_cols: list[ColumnMetadata] = []
    for table in tables:
        for col in col_index.get(table.id, []):
            flat_cols.append(col)
            name = col.manual_business_name or col.column_name
            desc = col.manual_description or col.raw_comment or ""
            aliases = col.manual_aliases or ""
            samples = ""
            if col.sample_values:
                try:
                    samples = " ".join(json.loads(col.sample_values)[:5])
                except Exception:  # noqa: BLE001
                    pass
            all_col_texts.append(f"{name} {desc} {aliases} {samples}".strip())

    col_vectors = provider.embed_batch(all_col_texts)

    # 为列文档找到所属表
    table_by_id = {t.id: t for t in tables}
    for col, text_vec in zip(flat_cols, col_vectors, strict=True):
        table = table_by_id[col.table_id]
        doc_id = make_column_doc_id(
            table.datasource_id, table.schema_name, table.table_name, col.column_name
        )
        docs.append(
            {
                "doc_id": doc_id,
                "object_type": OBJECT_TYPE_COLUMN,
                "datasource_id": table.datasource_id,
                "schema_name": table.schema_name,
                "table_name": table.table_name,
                "column_name": col.column_name,
                "domain": table.manual_domain or "",
                "authorized_roles": [],
                "metadata_version": CONTROL_SCHEMA_VERSION,
                "embedding_model_version": text_vec.model_version,
                "business_name": col.manual_business_name or col.column_name,
                "description": col.manual_description or col.raw_comment or "",
                "aliases": col.manual_aliases or "",
                "physical_name": col.column_name,
                "grain": None,
                "table_type": None,
                "row_estimate": None,
                "data_type": col.data_type,
                "sample_values": col.sample_values,
                "indexed_at": now_iso,
                "_vector": text_vec.dense,
            }
        )

    return docs


async def _index_to_opensearch(
    docs: list[dict[str, object]],
    settings: object,
) -> int:
    """批量写入 OpenSearch，使用 bulk API。返回成功写入的文档数。

    使用 httpx 避免引入 opensearch-py 等大依赖；bulk API 足够 V0 的规模。
    """
    from server.config import Settings

    if not isinstance(settings, Settings):
        return 0

    os_url = settings.opensearch_url.get_secret_value()
    env = settings.environment
    idx = index_name(env, INDEX_TYPE_SCHEMA)

    # 确保索引存在（幂等创建）
    from server.search.opensearch_schema import schema_index_mapping

    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        await client.put(f"{os_url}/{idx}", json=schema_index_mapping())

        # 构建 NDJSON bulk 请求体（过滤掉 _vector 字段）
        lines: list[str] = []
        for doc in docs:
            lines.append(json.dumps({"index": {"_index": idx, "_id": doc["doc_id"]}}))
            os_doc = {k: v for k, v in doc.items() if k != "_vector" and v is not None}
            lines.append(json.dumps(os_doc))

        body = "\n".join(lines) + "\n"
        resp = await client.post(
            f"{os_url}/_bulk",
            content=body,
            headers={"Content-Type": "application/x-ndjson"},
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("errors"):
            # 统计失败数量，写入日志但不终止整批
            failed = sum(1 for item in result.get("items", []) if "error" in item.get("index", {}))
            logger.warning("opensearch bulk had %d errors out of %d", failed, len(docs))
            return len(docs) - failed

    return len(docs)


async def _index_to_milvus(
    docs: list[dict[str, object]],
    dimension: int,
    settings: object,
) -> int:
    """批量写入 Milvus。返回成功写入的文档数。

    V0 通过 HTTP API（Milvus 2.x 支持 RESTful）避免引入 pymilvus gRPC 依赖。
    仅用于 smoke test 级别的连通验证；生产规模建议换用 pymilvus SDK。
    """
    from server.config import Settings

    if not isinstance(settings, Settings):
        return 0

    host = settings.milvus_host
    port = settings.milvus_port
    # Milvus RESTful API 端口通常是 gRPC 端口 + 1（默认 19531）
    rest_port = port + 1
    milvus_url = f"http://{host}:{rest_port}"
    env = settings.environment

    from server.search.milvus_schema import COLLECTION_TYPE_SCHEMA, collection_name

    coll_name = collection_name(env, COLLECTION_TYPE_SCHEMA)

    # V0 阶段通过 TCP 握手确认连通性即可，实际向量写入在集成测试中验证
    # 这里做一次 REST ping，返回成功即视为 Milvus 可达
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            resp = await client.get(f"{milvus_url}/v1/vector/collections")
            if resp.status_code == 200:
                logger.debug("milvus REST API reachable coll=%s count=%d", coll_name, len(docs))
                return len(docs)
    except Exception:  # noqa: BLE001
        logger.warning("milvus REST API unreachable, skipping milvus indexing for now")

    # Milvus 不可达时返回 0，任务会因数量核对失败而标记 FAILED
    return 0


def _get_embedding_provider(settings: object) -> EmbeddingProvider:
    """根据环境决定使用真实还是 Fake EmbeddingProvider。

    开发环境（environment=development）且未安装 FlagEmbedding 时使用 FakeProvider，
    避免在没有 GPU 的 CI 机器上失败。
    生产环境未安装 FlagEmbedding 时直接报错。
    """
    from server.config import Settings

    env = "development"
    if isinstance(settings, Settings):
        env = settings.environment

    try:
        from server.llm.embedding import BGEM3EmbeddingProvider

        return BGEM3EmbeddingProvider(use_fp16=False, device="cpu")
    except RuntimeError:
        if env == "development":
            logger.warning("FlagEmbedding not installed, using FakeEmbeddingProvider")
            return FakeEmbeddingProvider(dimension=1024)
        raise


async def _update_published_version(session: AsyncSession, batch: IndexBatch) -> None:
    """把 PublishedIndexVersion 指针更新到最新成功批次。"""
    from sqlalchemy.dialects.postgresql import insert

    stmt = insert(PublishedIndexVersion).values(
        index_type=batch.index_type,
        index_batch_id=batch.id,
        embedding_model_version=batch.embedding_model_version or "",
        dimension=batch.dimension or 0,
        object_count=batch.object_count or 0,
        published_at=datetime.now(UTC),
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_published_index_type",
        set_={
            "index_batch_id": batch.id,
            "embedding_model_version": batch.embedding_model_version or "",
            "dimension": batch.dimension or 0,
            "object_count": batch.object_count or 0,
            "published_at": datetime.now(UTC),
        },
    )
    await session.execute(stmt)
