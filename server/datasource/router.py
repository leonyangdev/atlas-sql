"""数据源管理 API 路由。

所有写入接口只允许管理员访问（V4 实现真实认证前用 x-admin-token 简单校验）。
响应体永远不回显凭据引用解析后的实际连接串，只返回 credential_ref 引用字符串本身。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.datasource.credentials import CredentialError, check_min_privileges, resolve_credential
from server.datasource.models import (
    DataSource,
    DataSourceKind,
    DataSourceStatus,
    MetadataSyncJob,
    SyncStatus,
)
from server.datasource.sync import SyncError, run_metadata_sync

router = APIRouter(prefix="/api/v1/datasources", tags=["datasource"])

# ---------------------------------------------------------------------------
# 请求与响应 Schema
# ---------------------------------------------------------------------------


class DataSourceCreate(BaseModel):
    """创建数据源的请求体。credential_ref 只接受 env: 或 vault: 前缀的安全引用。"""

    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=128)
    kind: DataSourceKind
    host: str = Field(..., max_length=256)
    port: int = Field(..., ge=1, le=65535)
    database_name: str = Field(..., min_length=1, max_length=128)
    credential_ref: str = Field(..., max_length=256)
    description: str | None = Field(default=None, max_length=2048)


class DataSourceUpdate(BaseModel):
    """可更新的字段子集；slug 和 kind 不允许修改。"""

    name: str | None = Field(default=None, max_length=128)
    host: str | None = Field(default=None, max_length=256)
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = Field(default=None, max_length=128)
    credential_ref: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=2048)
    status: DataSourceStatus | None = None


class DataSourceResponse(BaseModel):
    """响应体；credential_ref 只返回引用字符串，不解析为明文。"""

    id: int
    slug: str
    name: str
    kind: DataSourceKind
    host: str
    port: int
    database_name: str
    credential_ref: str
    status: DataSourceStatus
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectionTestResponse(BaseModel):
    ok: bool
    latency_ms: float
    error_kind: str | None = None


class TriggerSyncResponse(BaseModel):
    job_id: int
    idempotency_key: str
    status: SyncStatus


# ---------------------------------------------------------------------------
# 依赖项
# ---------------------------------------------------------------------------


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    """V0 阶段简单的管理员令牌校验。V4 替换为真实 RBAC。

    管理员令牌从环境变量 ATLAS_ADMIN_TOKEN 读取；如果未配置则拒绝所有写操作。
    """
    import os

    expected = os.environ.get("ATLAS_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin token is not configured",
        )
    if x_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid or missing admin token",
        )


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """从 app.state 获取 session 工厂并产出会话。"""
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# 路由处理器
# ---------------------------------------------------------------------------


@router.get("", response_model=list[DataSourceResponse])
async def list_datasources(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[DataSourceResponse]:
    """返回全部数据源列表。"""
    result = await session.execute(select(DataSource).order_by(DataSource.id))
    return [DataSourceResponse.model_validate(ds) for ds in result.scalars()]


@router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_datasource(
    body: DataSourceCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[None, Depends(require_admin)],
) -> DataSourceResponse:
    """登记新数据源。重复 slug 返回 409。凭据引用格式不合法返回 422。"""
    # 校验凭据引用格式（不实际解析）
    if not (body.credential_ref.startswith("env:") or body.credential_ref.startswith("vault:")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="credential_ref must start with 'env:' or 'vault:'",
        )

    # 检查 slug 是否重复
    existing = await session.execute(select(DataSource).where(DataSource.slug == body.slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"datasource slug '{body.slug}' already exists",
        )

    ds = DataSource(
        slug=body.slug,
        name=body.name,
        kind=body.kind,
        host=body.host,
        port=body.port,
        database_name=body.database_name,
        credential_ref=body.credential_ref,
        description=body.description,
        status=DataSourceStatus.ACTIVE,
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return DataSourceResponse.model_validate(ds)


@router.get("/{slug}", response_model=DataSourceResponse)
async def get_datasource(
    slug: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DataSourceResponse:
    """按 slug 查询数据源。"""
    ds = await _get_or_404(session, slug)
    return DataSourceResponse.model_validate(ds)


@router.patch("/{slug}", response_model=DataSourceResponse)
async def update_datasource(
    slug: str,
    body: DataSourceUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[None, Depends(require_admin)],
) -> DataSourceResponse:
    """部分更新数据源字段。"""
    ds = await _get_or_404(session, slug)
    update_data = body.model_dump(exclude_none=True)
    for field_name, value in update_data.items():
        setattr(ds, field_name, value)
    await session.commit()
    await session.refresh(ds)
    return DataSourceResponse.model_validate(ds)


@router.post("/{slug}/test-connection", response_model=ConnectionTestResponse)
async def test_connection(
    slug: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[None, Depends(require_admin)],
) -> ConnectionTestResponse:
    """测试数据源连接可达性并验证最小权限。响应不回显连接串。"""
    import time

    import asyncpg

    ds = await _get_or_404(session, slug)

    try:
        source_url = resolve_credential(ds.credential_ref)
    except CredentialError as exc:
        return ConnectionTestResponse(ok=False, latency_ms=0, error_kind=str(exc))

    check_min_privileges(ds.credential_ref)

    dsn = source_url.replace("postgresql+asyncpg://", "postgresql://")
    started = time.perf_counter()
    try:
        conn = await asyncpg.connect(dsn=dsn, timeout=10)
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return ConnectionTestResponse(ok=True, latency_ms=latency_ms)
    except asyncpg.InvalidAuthorizationSpecificationError:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return ConnectionTestResponse(ok=False, latency_ms=latency_ms, error_kind="auth_error")
    except (OSError, ConnectionError):
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return ConnectionTestResponse(
            ok=False, latency_ms=latency_ms, error_kind="connection_error"
        )
    except Exception:  # noqa: BLE001
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return ConnectionTestResponse(ok=False, latency_ms=latency_ms, error_kind="unknown_error")


@router.post(
    "/{slug}/sync", response_model=TriggerSyncResponse, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_sync(
    slug: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[None, Depends(require_admin)],
) -> TriggerSyncResponse:
    """触发元数据同步任务。

    如果 Celery 已配置则派发后台任务；否则同步执行（方便开发环境和测试）。
    调用方可以用 job_id 轮询 /sync-jobs/{id} 查询状态。
    """
    ds = await _get_or_404(session, slug)

    idempotency_key = str(uuid.uuid4())
    job = MetadataSyncJob(
        datasource_id=ds.id,
        idempotency_key=idempotency_key,
        status=SyncStatus.PENDING,
    )
    session.add(job)
    await session.flush()
    job_id = job.id

    # 尝试派发 Celery 任务；未配置时同步执行
    dispatched = await _try_dispatch_celery_task(slug, job_id, idempotency_key)
    if not dispatched:
        # 开发/测试环境：同步执行
        try:
            source_url = resolve_credential(ds.credential_ref)
        except CredentialError as exc:
            job.status = SyncStatus.FAILED
            job.error_summary = str(exc)
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

        try:
            await run_metadata_sync(session, ds, job, source_url)
        except SyncError:
            pass  # error 已记录在 job.error_summary

    await session.commit()
    return TriggerSyncResponse(
        job_id=job_id,
        idempotency_key=idempotency_key,
        status=job.status,
    )


@router.get("/{slug}/sync-jobs", response_model=list[dict[str, object]])
async def list_sync_jobs(
    slug: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[dict[str, object]]:
    """返回指定数据源的最近 20 次同步任务记录。"""
    ds = await _get_or_404(session, slug)
    result = await session.execute(
        select(MetadataSyncJob)
        .where(MetadataSyncJob.datasource_id == ds.id)
        .order_by(MetadataSyncJob.id.desc())
        .limit(20)
    )
    jobs = result.scalars().all()
    return [
        {
            "id": j.id,
            "idempotency_key": j.idempotency_key,
            "status": j.status.value,
            "retry_count": j.retry_count,
            "tables_discovered": j.tables_discovered,
            "columns_discovered": j.columns_discovered,
            "error_summary": j.error_summary,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }
        for j in jobs
    ]


async def _get_or_404(session: AsyncSession, slug: str) -> DataSource:
    result = await session.execute(select(DataSource).where(DataSource.slug == slug))
    ds = result.scalar_one_or_none()
    if ds is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"datasource '{slug}' not found",
        )
    return ds


async def _try_dispatch_celery_task(slug: str, job_id: int, idempotency_key: str) -> bool:
    """尝试派发 Celery 任务；Celery 未配置时返回 False。"""
    try:
        from server.tasks.metadata_sync import sync_datasource_task

        sync_datasource_task.apply_async(
            args=[slug, job_id],
            task_id=idempotency_key,
        )
        return True
    except ImportError:
        return False
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------
