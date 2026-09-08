"""元数据同步 Celery 任务。

任务接收数据源 slug 和 job_id，通过控制库更新 MetadataSyncJob 状态。
重试逻辑：每次重试前递增 retry_count；达到 MAX_RETRIES 后标记 FAILED 且不再重试。

任务与 ORM session 的关系：
- Celery worker 是独立进程，不能复用 FastAPI 的 session。
- 任务内部通过 AsyncSession 工厂创建短生命周期 session，结束后主动关闭。
- 任务不可复用 FastAPI 的 ``create_app()``，而是直接使用 ``create_control_engine``。
"""

from __future__ import annotations

import asyncio
import logging

from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.config import get_settings
from server.datasource.credentials import CredentialError, resolve_credential
from server.datasource.models import DataSource, MetadataSyncJob, SyncStatus
from server.datasource.sync import SyncError, run_metadata_sync
from server.db import create_control_engine
from server.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="atlas_sql.metadata_sync",
    max_retries=MAX_RETRIES,
    acks_late=True,
)
def sync_datasource_task(self: Task, slug: str, job_id: int) -> dict[str, object]:
    """采集指定数据源的元数据并更新控制库。

    Args:
        slug: 数据源唯一标识（用于日志和错误信息）。
        job_id: MetadataSyncJob 主键，任务从这里读取状态并写回结果。

    Returns:
        包含 job_id 和最终状态的字典，供 result_backend 保存。
    """
    return asyncio.run(_run_sync_async(self, slug, job_id))


async def _run_sync_async(task: Task, slug: str, job_id: int) -> dict[str, object]:
    """异步同步逻辑；由同步任务包装以兼容 Celery 的同步任务签名。"""
    settings = get_settings()
    engine = create_control_engine(settings.control_database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # 加载任务记录
            job_result = await session.execute(
                select(MetadataSyncJob).where(MetadataSyncJob.id == job_id)
            )
            job = job_result.scalar_one_or_none()
            if job is None:
                logger.error("sync job not found job_id=%d", job_id)
                return {"job_id": job_id, "status": "not_found"}

            # 加载数据源
            ds_result = await session.execute(select(DataSource).where(DataSource.slug == slug))
            ds = ds_result.scalar_one_or_none()
            if ds is None:
                job.status = SyncStatus.FAILED
                job.error_summary = f"datasource '{slug}' not found"
                await session.commit()
                return {"job_id": job_id, "status": "failed"}

            # 解析凭据
            try:
                source_url = resolve_credential(ds.credential_ref)
            except CredentialError as exc:
                job.status = SyncStatus.FAILED
                job.error_summary = str(exc)
                await session.commit()
                return {"job_id": job_id, "status": "failed"}

            # 执行同步
            try:
                await run_metadata_sync(session, ds, job, source_url)
                await session.commit()
                return {"job_id": job_id, "status": "succeeded"}
            except SyncError as exc:
                # 更新重试计数
                job.retry_count += 1
                await session.commit()

                if job.retry_count < MAX_RETRIES:
                    logger.warning(
                        "sync failed, will retry slug=%s retry=%d/%d error=%s",
                        slug,
                        job.retry_count,
                        MAX_RETRIES,
                        exc,
                    )
                    raise task.retry(exc=exc, countdown=60 * job.retry_count) from exc
                else:
                    logger.error(
                        "sync failed after %d retries slug=%s error=%s",
                        MAX_RETRIES,
                        slug,
                        exc,
                    )
                    return {"job_id": job_id, "status": "failed"}
    finally:
        await engine.dispose()
