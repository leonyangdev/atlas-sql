"""V3 语义层管理 API。

提供指标生命周期管理、版本查询与对比、Verified Query 管理接口。
所有写操作需要 x-admin-token 认证。
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import get_settings
from server.semantic.lifecycle import (
    InvalidTransitionError,
    LifecycleError,
    MetricLifecycleService,
    PublishedImmutableError,
    RegressionNotPassedError,
)
from server.semantic.models import (
    MetricDefinition,
    MetricVersion,
    SemanticStatus,
    VerifiedQuery,
    VerifiedQueryStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/semantic", tags=["semantic"])


# ──────────────────────────────────────────────────────────────
# 依赖项
# ──────────────────────────────────────────────────────────────


async def _get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """从 app.state 获取控制库 session（与 datasource router 同一模式）。"""
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


def _require_admin(x_admin_token: str | None = Header(default=None, alias="x-admin-token")) -> None:
    expected = os.environ.get("ATLAS_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="admin token is not configured")
    if x_admin_token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid or missing admin token")


# ──────────────────────────────────────────────────────────────
# 请求/响应 Schema
# ──────────────────────────────────────────────────────────────


class MetricSummary(BaseModel):
    metric_id: str
    label: str
    domain: str
    grain: str
    status: str
    version_number: int | None
    updated_at: str


class MetricDetail(MetricSummary):
    expression: str
    required_filters: list[str]
    synonyms: list[str]
    is_sensitive: bool
    time_rule_note: str | None
    warning: str | None


class TransitionRequest(BaseModel):
    target_status: str = Field(..., description="目标状态：draft / testing / published / deprecated")
    operator: str = Field(default="admin")


class PublishRequest(BaseModel):
    published_by: str
    regression_run_id: str | None = None
    change_note: str | None = None
    require_regression: bool = Field(
        default=True, description="是否强制绑定回归测试 ID（生产环境应为 True）"
    )


class RollbackRequest(BaseModel):
    target_version: int
    operator: str = Field(default="admin")


class VersionDiffResponse(BaseModel):
    metric_id: str
    version_a: int
    version_b: int
    diff: dict


class VerifiedQuerySummary(BaseModel):
    query_id: str
    question: str
    domain: str
    status: str
    tags: list[str]
    verified_by: str | None
    verified_at: str | None
    is_test_locked: bool


class VerifyQueryRequest(BaseModel):
    verified_by: str


class InvalidateQueryRequest(BaseModel):
    reason: str


# ──────────────────────────────────────────────────────────────
# 指标管理端点
# ──────────────────────────────────────────────────────────────


@router.get("/metrics", response_model=list[MetricSummary])
async def list_metrics(  # pragma: no cover
    domain: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(_get_session),
) -> list[MetricSummary]:
    """列出所有指标定义（支持按域和状态过滤）。"""
    stmt = select(MetricDefinition)
    if domain:
        stmt = stmt.where(MetricDefinition.domain == domain)
    if status:
        try:
            s = SemanticStatus(status)
            stmt = stmt.where(MetricDefinition.status == s)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的状态值：{status}")

    result = await session.execute(stmt.order_by(MetricDefinition.domain, MetricDefinition.metric_id))
    metrics = result.scalars().all()

    summaries = []
    for m in metrics:
        # 查询当前 active version
        from server.semantic.models import MetricActiveVersion
        av_result = await session.execute(
            select(MetricActiveVersion.version_number).where(
                MetricActiveVersion.metric_id == m.metric_id
            )
        )
        av = av_result.scalar_one_or_none()
        summaries.append(
            MetricSummary(
                metric_id=m.metric_id,
                label=m.label,
                domain=m.domain,
                grain=m.grain.value if hasattr(m.grain, "value") else str(m.grain),
                status=m.status.value if hasattr(m.status, "value") else str(m.status),
                version_number=av,
                updated_at=m.updated_at.isoformat(),
            )
        )
    return summaries


@router.get("/metrics/{metric_id}", response_model=MetricDetail)
async def get_metric(  # pragma: no cover
    metric_id: str,
    session: AsyncSession = Depends(_get_session),
) -> MetricDetail:
    """获取指标详情。"""
    result = await session.execute(
        select(MetricDefinition).where(MetricDefinition.metric_id == metric_id)
    )
    m = result.scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail=f"指标 '{metric_id}' 不存在。")

    from server.semantic.models import MetricActiveVersion
    av_result = await session.execute(
        select(MetricActiveVersion.version_number).where(
            MetricActiveVersion.metric_id == metric_id
        )
    )
    av = av_result.scalar_one_or_none()

    return MetricDetail(
        metric_id=m.metric_id,
        label=m.label,
        domain=m.domain,
        grain=m.grain.value if hasattr(m.grain, "value") else str(m.grain),
        status=m.status.value if hasattr(m.status, "value") else str(m.status),
        version_number=av,
        updated_at=m.updated_at.isoformat(),
        expression=m.expression,
        required_filters=m.required_filters or [],
        synonyms=m.synonyms or [],
        is_sensitive=m.is_sensitive,
        time_rule_note=m.time_rule_note,
        warning=m.warning,
    )


@router.post("/metrics/{metric_id}/transition", status_code=200)
async def transition_metric(  # pragma: no cover
    metric_id: str,
    body: TransitionRequest,
    session: AsyncSession = Depends(_get_session),
    _: str = Depends(_require_admin),
) -> dict:
    """执行指标状态转移（DRAFT↔TESTING）。"""
    try:
        target = SemanticStatus(body.target_status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的目标状态：{body.target_status}")

    svc = MetricLifecycleService()
    try:
        await svc.transition(metric_id, target, session, operator=body.operator)
        await session.commit()
        return {"metric_id": metric_id, "status": body.target_status, "ok": True}
    except (InvalidTransitionError, PublishedImmutableError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LifecycleError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/metrics/{metric_id}/publish", status_code=200)
async def publish_metric(  # pragma: no cover
    metric_id: str,
    body: PublishRequest,
    session: AsyncSession = Depends(_get_session),
    _: str = Depends(_require_admin),
) -> dict:
    """发布指标（TESTING → PUBLISHED），创建不可变版本快照并切换 active_version。"""
    svc = MetricLifecycleService()
    try:
        result = await svc.publish(
            metric_id,
            body.published_by,
            session,
            regression_run_id=body.regression_run_id,
            change_note=body.change_note,
            require_regression=body.require_regression,
        )
        await session.commit()
        return {
            "metric_id": result.metric_id,
            "version_number": result.version_number,
            "previous_version": result.previous_version,
            "change_note": result.change_note,
            "ok": True,
        }
    except RegressionNotPassedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LifecycleError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/metrics/{metric_id}/rollback", status_code=200)
async def rollback_metric(  # pragma: no cover
    metric_id: str,
    body: RollbackRequest,
    session: AsyncSession = Depends(_get_session),
    _: str = Depends(_require_admin),
) -> dict:
    """回滚 active_version 到指定历史版本。"""
    svc = MetricLifecycleService()
    try:
        result = await svc.rollback(
            metric_id, body.target_version, session, operator=body.operator
        )
        await session.commit()
        return {
            "metric_id": result.metric_id,
            "rolled_back_to_version": result.rolled_back_to_version,
            "previous_version": result.previous_version,
            "ok": True,
        }
    except LifecycleError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/metrics/{metric_id}/versions")
async def list_metric_versions(  # pragma: no cover
    metric_id: str,
    session: AsyncSession = Depends(_get_session),
) -> list[dict]:
    """列出指标所有版本历史。"""
    return await MetricLifecycleService.list_versions(metric_id, session)


@router.get("/metrics/{metric_id}/versions/diff")
async def diff_metric_versions(  # pragma: no cover
    metric_id: str,
    version_a: int,
    version_b: int,
    session: AsyncSession = Depends(_get_session),
) -> VersionDiffResponse:
    """对比两个版本快照的差异。"""
    try:
        diff = await MetricLifecycleService.get_version_diff(
            metric_id, version_a, version_b, session
        )
        return VersionDiffResponse(
            metric_id=metric_id,
            version_a=version_a,
            version_b=version_b,
            diff=diff,
        )
    except LifecycleError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ──────────────────────────────────────────────────────────────
# Verified Query 管理端点
# ──────────────────────────────────────────────────────────────


@router.get("/verified-queries", response_model=list[VerifiedQuerySummary])
async def list_verified_queries(  # pragma: no cover
    domain: str | None = None,
    status: str | None = None,
    is_test_locked: bool | None = None,
    session: AsyncSession = Depends(_get_session),
) -> list[VerifiedQuerySummary]:
    """列出可信查询样例（支持过滤）。"""
    stmt = select(VerifiedQuery)
    if domain:
        stmt = stmt.where(VerifiedQuery.domain == domain)
    if status:
        try:
            s = VerifiedQueryStatus(status)
            stmt = stmt.where(VerifiedQuery.status == s)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的状态值：{status}")
    if is_test_locked is not None:
        stmt = stmt.where(VerifiedQuery.is_test_locked == is_test_locked)

    result = await session.execute(stmt.order_by(VerifiedQuery.domain, VerifiedQuery.created_at))
    queries = result.scalars().all()

    return [
        VerifiedQuerySummary(
            query_id=q.query_id,
            question=q.question,
            domain=q.domain,
            status=q.status.value if hasattr(q.status, "value") else str(q.status),
            tags=q.tags or [],
            verified_by=q.verified_by,
            verified_at=q.verified_at.isoformat() if q.verified_at else None,
            is_test_locked=q.is_test_locked,
        )
        for q in queries
    ]


@router.post("/verified-queries/{query_id}/verify", status_code=200)
async def verify_query(  # pragma: no cover
    query_id: str,
    body: VerifyQueryRequest,
    session: AsyncSession = Depends(_get_session),
    _: str = Depends(_require_admin),
) -> dict:
    """将 DRAFT 样例标记为 VERIFIED（审核通过）。"""
    result = await session.execute(
        select(VerifiedQuery).where(VerifiedQuery.query_id == query_id)
    )
    vq = result.scalar_one_or_none()
    if vq is None:
        raise HTTPException(status_code=404, detail=f"样例 '{query_id}' 不存在。")
    if vq.status != VerifiedQueryStatus.DRAFT:
        raise HTTPException(
            status_code=409,
            detail=f"只有 DRAFT 状态的样例可以审核通过，当前状态为 '{vq.status}'。",
        )

    vq.status = VerifiedQueryStatus.VERIFIED
    vq.verified_by = body.verified_by
    vq.verified_at = datetime.now(UTC)
    vq.updated_at = datetime.now(UTC)
    await session.commit()
    return {"query_id": query_id, "status": "verified", "ok": True}


@router.post("/verified-queries/{query_id}/invalidate", status_code=200)
async def invalidate_query(  # pragma: no cover
    query_id: str,
    body: InvalidateQueryRequest,
    session: AsyncSession = Depends(_get_session),
    _: str = Depends(_require_admin),
) -> dict:
    """手动将样例标记为 INVALID。"""
    result = await session.execute(
        select(VerifiedQuery).where(VerifiedQuery.query_id == query_id)
    )
    vq = result.scalar_one_or_none()
    if vq is None:
        raise HTTPException(status_code=404, detail=f"样例 '{query_id}' 不存在。")

    vq.status = VerifiedQueryStatus.INVALID
    vq.invalidation_reason = body.reason
    vq.updated_at = datetime.now(UTC)
    await session.commit()
    return {"query_id": query_id, "status": "invalid", "ok": True}
