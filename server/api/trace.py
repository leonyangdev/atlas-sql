"""管理员 Trace 列表、详情与人工失败归因 API。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.datasource.router import require_admin
from server.domain.query import QueryStatus
from server.observability.failure import FailureCategory
from server.query.models import QueryRecord

router = APIRouter(prefix="/api/v1/admin/traces", tags=["trace"])


class TraceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trace_id: str
    question: str
    identity: str
    status: QueryStatus
    error_code: str | None
    model_version: str
    prompt_version: str | None
    total_tokens: int
    execution_ms: float | None
    failure_category: str | None
    created_at: datetime


class TraceDetail(TraceListItem):
    sql: str | None
    error_message: str | None
    data_version: str
    schema_version: str
    prompt_hash: str | None
    model_parameters: dict[str, str | int | float | bool]
    referenced_tables: list[str]
    referenced_columns: list[str]
    stages: list[dict[str, str | float | None]]
    review_note: str | None
    reviewed_at: datetime | None


class TraceReview(BaseModel):
    failure_category: FailureCategory
    note: str | None = Field(default=None, max_length=2_000)


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.db_session_factory() as session:
        yield session


@router.get("", response_model=list[TraceListItem])
async def list_traces(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[None, Depends(require_admin)],
    query_status: Annotated[QueryStatus | None, Query(alias="status")] = None,
    failure_category: FailureCategory | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[TraceListItem]:
    """按时间倒序返回 Trace，支持状态和失败类别过滤。"""

    statement = select(QueryRecord)
    if query_status is not None:
        statement = statement.where(QueryRecord.status == query_status)
    if failure_category is not None:
        statement = statement.where(QueryRecord.failure_category == failure_category.value)
    result = await session.execute(statement.order_by(QueryRecord.id.desc()).limit(limit))
    return [TraceListItem.model_validate(record) for record in result.scalars()]


@router.get("/{trace_id}", response_model=TraceDetail)
async def get_trace(
    trace_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[None, Depends(require_admin)],
) -> TraceDetail:
    record = await _get_record(session, trace_id)
    return TraceDetail.model_validate(record)


@router.patch("/{trace_id}/review", response_model=TraceDetail)
async def review_trace(
    trace_id: uuid.UUID,
    body: TraceReview,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[None, Depends(require_admin)],
) -> TraceDetail:
    """保存人工复核标签；备注为可选且不接收底层异常。"""

    record = await _get_record(session, trace_id)
    record.failure_category = body.failure_category.value
    record.review_note = body.note.strip() if body.note else None
    record.reviewed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(record)
    return TraceDetail.model_validate(record)


async def _get_record(session: AsyncSession, trace_id: uuid.UUID) -> QueryRecord:
    result = await session.execute(
        select(QueryRecord).where(QueryRecord.trace_id == str(trace_id))
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")
    return record
