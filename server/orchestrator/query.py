"""V1 查询编排器。

编排器只做阶段顺序、上下文传递和状态落库，不包含 Provider、Prompt 或 SQL 实现。下一故事
通过 ``QueryPipeline`` 端口接入生成链路，因此切换模型不会修改这里。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from server.domain.query import (
    QueryColumn,
    QueryError,
    QueryErrorCode,
    QueryRequest,
    QueryResponse,
    QueryStageTrace,
    QueryStatus,
    QueryTrace,
)
from server.domain.sales_scope import assess_sales_scope
from server.query.repository import QueryRepository, QueryState


@dataclass(frozen=True)
class QueryContext:
    """传给每个后续阶段的不可变运行上下文。"""

    trace_id: uuid.UUID
    identity: str
    data_version: str
    schema_version: str
    model_version: str
    timeout_ms: int
    metric_ids: tuple[str, ...]


@dataclass(frozen=True)
class QueryOutcome:
    """生成/校验/执行链路返回给编排器的统一结果。"""

    status: QueryStatus
    sql: str | None = None
    columns: tuple[QueryColumn, ...] = ()
    rows: tuple[tuple[str | int | float | bool | None, ...], ...] = ()
    error_code: QueryErrorCode | None = None
    error_message: str | None = None
    truncated: bool = False
    prompt_version: str | None = None
    prompt_hash: str | None = None
    model_version: str | None = None
    model_parameters: dict[str, str | int | float | bool] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    provider_request_id: str | None = None
    execution_ms: float | None = None
    referenced_tables: tuple[str, ...] = ()
    referenced_columns: tuple[str, ...] = ()
    stages: tuple[QueryStageTrace, ...] = ()
    summary: str | None = None


class QueryPipeline(Protocol):
    """后续 V1 故事实现的受控生成与执行端口。"""

    async def run(self, request: QueryRequest, context: QueryContext) -> QueryOutcome: ...


class QueryOrchestrator:
    """串联范围判断、生成链路和状态持久化。"""

    def __init__(
        self,
        repository: QueryRepository,
        *,
        data_version: str,
        schema_version: str,
        model_version: str,
        timeout_ms: int,
        pipeline: QueryPipeline | None = None,
    ) -> None:
        self._repository = repository
        self._data_version = data_version
        self._schema_version = schema_version
        self._model_version = model_version
        self._timeout_ms = timeout_ms
        self._pipeline = pipeline

    async def submit(self, request: QueryRequest, identity: str) -> QueryResponse:
        """接收一次请求并返回当前状态。

        没有配置 pipeline 时保留 ``processing``，明确表示 S01 已接收但生成阶段尚未接入。
        生产环境中的内部异常统一转换为稳定错误码，不把异常文本暴露给用户。
        """

        now = datetime.now(UTC)
        state = QueryState(
            trace_id=request.trace_id or uuid.uuid4(),
            session_id=request.session_id,
            identity=identity,
            question=request.question,
            status=QueryStatus.PROCESSING,
            data_version=self._data_version,
            schema_version=self._schema_version,
            model_version=self._model_version,
            timeout_ms=self._timeout_ms,
            created_at=now,
            updated_at=now,
        )
        try:
            await self._repository.create(state)
            decision = assess_sales_scope(request.question)
            state = replace(
                state,
                status=decision.status,
                metric_ids=decision.metric_ids,
                error_code=decision.error_code,
                error_message=decision.message,
                updated_at=datetime.now(UTC),
            )
            await self._repository.update(state)

            if decision.status != QueryStatus.PROCESSING or self._pipeline is None:
                return response_from_state(state)

            context = QueryContext(
                trace_id=state.trace_id,
                identity=identity,
                data_version=state.data_version,
                schema_version=state.schema_version,
                model_version=state.model_version,
                timeout_ms=state.timeout_ms,
                metric_ids=state.metric_ids,
            )
            outcome = await self._pipeline.run(request, context)
            state = replace(
                state,
                status=outcome.status,
                sql=outcome.sql,
                columns=outcome.columns,
                rows=outcome.rows,
                error_code=outcome.error_code,
                error_message=outcome.error_message,
                truncated=outcome.truncated,
                prompt_version=outcome.prompt_version,
                prompt_hash=outcome.prompt_hash,
                model_version=outcome.model_version or state.model_version,
                model_parameters=outcome.model_parameters or {},
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                total_tokens=outcome.total_tokens,
                provider_request_id=outcome.provider_request_id,
                execution_ms=outcome.execution_ms,
                referenced_tables=outcome.referenced_tables,
                referenced_columns=outcome.referenced_columns,
                stages=outcome.stages,
                summary=outcome.summary,
                updated_at=datetime.now(UTC),
            )
            await self._repository.update(state)
            return response_from_state(state)
        except Exception:  # noqa: BLE001 -- 边界层必须把未知异常转换为安全响应
            failed = replace(
                state,
                status=QueryStatus.FAILED,
                error_code=QueryErrorCode.INTERNAL_ERROR,
                error_message="查询处理失败，请使用 trace_id 联系管理员。",
                updated_at=datetime.now(UTC),
            )
            try:
                await self._repository.update(failed)
            except Exception:  # noqa: BLE001 -- 原始失败优先，避免二次持久化覆盖安全响应
                pass
            return response_from_state(failed)

    async def get(self, trace_id: uuid.UUID, identity: str) -> QueryResponse | None:
        """只允许请求身份读取自己的状态，避免用 trace_id 枚举他人请求。"""

        state = await self._repository.get(trace_id)
        if state is None or state.identity != identity:
            return None
        return response_from_state(state)


def response_from_state(state: QueryState) -> QueryResponse:
    """从内部快照构造稳定 API 契约。"""

    error = None
    if state.error_code is not None and state.error_message is not None:
        error = QueryError(code=state.error_code, message=state.error_message)
    trace = QueryTrace(
        trace_id=state.trace_id,
        identity=state.identity,
        status=state.status,
        data_version=state.data_version,
        schema_version=state.schema_version,
        model_version=state.model_version,
        timeout_ms=state.timeout_ms,
        prompt_version=state.prompt_version,
        prompt_hash=state.prompt_hash,
        model_parameters=state.model_parameters,
        input_tokens=state.input_tokens,
        output_tokens=state.output_tokens,
        total_tokens=state.total_tokens,
        execution_ms=state.execution_ms,
        referenced_tables=list(state.referenced_tables),
        referenced_columns=list(state.referenced_columns),
        metric_ids=list(state.metric_ids),
        stages=[QueryStageTrace(name="scope", status="succeeded"), *state.stages],
        created_at=state.created_at,
        updated_at=state.updated_at,
    )
    return QueryResponse(
        question=state.question,
        session_id=state.session_id,
        trace_id=state.trace_id,
        status=state.status,
        sql=state.sql,
        columns=list(state.columns),
        rows=[list(row) for row in state.rows],
        error=error,
        truncated=state.truncated,
        execution_ms=state.execution_ms,
        referenced_tables=list(state.referenced_tables),
        referenced_columns=list(state.referenced_columns),
        summary=state.summary,
        trace=trace,
    )
