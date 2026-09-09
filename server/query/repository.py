"""问数状态仓储接口及 SQLAlchemy 实现。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.domain.query import QueryColumn, QueryErrorCode, QueryStageTrace, QueryStatus
from server.query.models import QueryRecord


@dataclass(frozen=True)
class QueryState:
    """编排器和持久化适配器之间的内部快照。"""

    trace_id: uuid.UUID
    session_id: str
    identity: str
    question: str
    status: QueryStatus
    data_version: str
    schema_version: str
    model_version: str
    timeout_ms: int
    created_at: datetime
    updated_at: datetime
    error_code: QueryErrorCode | None = None
    error_message: str | None = None
    sql: str | None = None
    columns: tuple[QueryColumn, ...] = ()
    rows: tuple[tuple[str | int | float | bool | None, ...], ...] = ()
    truncated: bool = False
    metric_ids: tuple[str, ...] = ()
    prompt_version: str | None = None
    prompt_hash: str | None = None
    model_parameters: dict[str, str | int | float | bool] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    provider_request_id: str | None = None
    execution_ms: float | None = None
    referenced_tables: tuple[str, ...] = ()
    referenced_columns: tuple[str, ...] = ()
    stages: tuple[QueryStageTrace, ...] = ()
    summary: str | None = None


class QueryRepository(Protocol):
    """编排器所需的最小持久化端口。"""

    async def create(self, state: QueryState) -> None: ...

    async def update(self, state: QueryState) -> None: ...

    async def get(self, trace_id: uuid.UUID) -> QueryState | None: ...


@dataclass
class InMemoryQueryRepository:
    """离线开发和单元测试使用的确定性仓储。"""

    records: dict[uuid.UUID, QueryState] = field(default_factory=dict)

    async def create(self, state: QueryState) -> None:
        if state.trace_id in self.records:
            raise ValueError("trace_id already exists")
        self.records[state.trace_id] = state

    async def update(self, state: QueryState) -> None:
        if state.trace_id not in self.records:
            raise KeyError("query record does not exist")
        self.records[state.trace_id] = state

    async def get(self, trace_id: uuid.UUID) -> QueryState | None:
        return self.records.get(trace_id)


class SQLAlchemyQueryRepository:
    """把 QueryState 保存到控制库。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, state: QueryState) -> None:
        self._session.add(_record_from_state(state))
        await self._session.commit()

    async def update(self, state: QueryState) -> None:
        result = await self._session.execute(
            select(QueryRecord).where(QueryRecord.trace_id == str(state.trace_id))
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise KeyError("query record does not exist")
        _apply_state(record, state)
        await self._session.commit()

    async def get(self, trace_id: uuid.UUID) -> QueryState | None:
        result = await self._session.execute(
            select(QueryRecord).where(QueryRecord.trace_id == str(trace_id))
        )
        record = result.scalar_one_or_none()
        return _state_from_record(record) if record is not None else None


def _record_from_state(state: QueryState) -> QueryRecord:
    record = QueryRecord(
        trace_id=str(state.trace_id),
        session_id=state.session_id,
        identity=state.identity,
        question=state.question,
        status=state.status,
        data_version=state.data_version,
        schema_version=state.schema_version,
        model_version=state.model_version,
        timeout_ms=state.timeout_ms,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )
    _apply_state(record, state)
    return record


def _apply_state(record: QueryRecord, state: QueryState) -> None:
    record.status = state.status
    record.error_code = state.error_code.value if state.error_code else None
    record.error_message = state.error_message
    record.sql = state.sql
    record.columns = [column.model_dump() for column in state.columns]
    record.rows = [list(row) for row in state.rows]
    record.truncated = state.truncated
    record.metric_ids = list(state.metric_ids)
    record.prompt_version = state.prompt_version
    record.prompt_hash = state.prompt_hash
    record.model_parameters = dict(state.model_parameters)
    record.input_tokens = state.input_tokens
    record.output_tokens = state.output_tokens
    record.total_tokens = state.total_tokens
    record.provider_request_id = state.provider_request_id
    record.execution_ms = state.execution_ms
    record.referenced_tables = list(state.referenced_tables)
    record.referenced_columns = list(state.referenced_columns)
    record.stages = [stage.model_dump() for stage in state.stages]
    record.summary = state.summary
    record.updated_at = state.updated_at


def _state_from_record(record: QueryRecord) -> QueryState:
    return QueryState(
        trace_id=uuid.UUID(record.trace_id),
        session_id=record.session_id,
        identity=record.identity,
        question=record.question,
        status=record.status,
        data_version=record.data_version,
        schema_version=record.schema_version,
        model_version=record.model_version,
        timeout_ms=record.timeout_ms,
        created_at=record.created_at,
        updated_at=record.updated_at,
        error_code=QueryErrorCode(record.error_code) if record.error_code else None,
        error_message=record.error_message,
        sql=record.sql,
        columns=tuple(QueryColumn.model_validate(column) for column in record.columns),
        rows=tuple(tuple(row) for row in record.rows),
        truncated=record.truncated,
        metric_ids=tuple(record.metric_ids),
        prompt_version=record.prompt_version,
        prompt_hash=record.prompt_hash,
        model_parameters=dict(record.model_parameters),
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        total_tokens=record.total_tokens,
        provider_request_id=record.provider_request_id,
        execution_ms=record.execution_ms,
        referenced_tables=tuple(record.referenced_tables),
        referenced_columns=tuple(record.referenced_columns),
        stages=tuple(QueryStageTrace.model_validate(stage) for stage in record.stages),
        summary=record.summary,
    )
