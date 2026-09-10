"""用户问数 API。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.domain.query import QueryRequest, QueryResponse, QueryStatus
from server.orchestrator.query import QueryOrchestrator
from server.query.repository import SQLAlchemyQueryRepository

router = APIRouter(prefix="/api/v1/query", tags=["query"])


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """为问数状态创建短生命周期控制库会话。"""

    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


async def get_query_orchestrator(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> QueryOrchestrator:
    """优先使用测试注入的编排器，否则组装真实控制库仓储。"""

    injected = request.app.state.query_orchestrator
    if injected is not None:
        return cast(QueryOrchestrator, injected)
    settings = request.app.state.settings
    pipeline = request.app.state.query_pipeline
    registry = getattr(request.app.state, "semantic_registry", None)
    return QueryOrchestrator(
        SQLAlchemyQueryRepository(session),
        data_version=settings.query_data_version,
        schema_version=settings.query_schema_version,
        model_version=pipeline.model_version,
        timeout_ms=settings.query_timeout_ms,
        pipeline=pipeline,
        registry=registry,
    )


def get_identity(
    x_atlas_identity: Annotated[str | None, Header(max_length=128)] = None,
) -> str:
    """V1 的临时身份入口；V4 将由认证中间件提供不可伪造身份。"""

    identity = (x_atlas_identity or "public").strip()
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="blank identity"
        )
    return identity


@router.post("", response_model=QueryResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_query(
    body: QueryRequest,
    response: Response,
    orchestrator: Annotated[QueryOrchestrator, Depends(get_query_orchestrator)],
    identity: Annotated[str, Depends(get_identity)],
) -> QueryResponse:
    """提交问题；同步完成、澄清或拒绝时返回 200，仍处理中返回 202。"""

    result = await orchestrator.submit(body, identity)
    if result.status != QueryStatus.PROCESSING:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/{trace_id}", response_model=QueryResponse)
async def get_query(
    trace_id: uuid.UUID,
    orchestrator: Annotated[QueryOrchestrator, Depends(get_query_orchestrator)],
    identity: Annotated[str, Depends(get_identity)],
) -> QueryResponse:
    """按 trace_id 查询当前身份自己的请求状态。"""

    result = await orchestrator.get(trace_id, identity)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="query not found")
    return result
