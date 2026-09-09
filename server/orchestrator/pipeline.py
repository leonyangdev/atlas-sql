"""V1 生成、校验与只读执行的完整安全流水线。"""

from __future__ import annotations

import time
from dataclasses import replace

from server.domain.query import QueryErrorCode, QueryRequest, QueryStageTrace, QueryStatus
from server.execution.postgres import QueryExecutionError, ReadOnlyQueryExecutor
from server.generation.answer import ResultSummaryBuilder
from server.orchestrator.query import QueryContext, QueryOutcome, QueryPipeline
from server.validation.sql import SQLValidationError, SQLValidator


class SafeQueryPipeline:
    """强制候选 SQL 依次经过 AST 校验和只读执行，不能跳过中间阶段。"""

    def __init__(
        self,
        generator: QueryPipeline,
        validator: SQLValidator,
        executor: ReadOnlyQueryExecutor,
        summary_builder: ResultSummaryBuilder | None = None,
    ) -> None:
        self._generator = generator
        self._validator = validator
        self._executor = executor
        self._summary_builder = summary_builder or ResultSummaryBuilder()

    @property
    def model_version(self) -> str:
        """向组合根暴露底层生成模型版本。"""

        return str(getattr(self._generator, "model_version", "unknown"))

    async def run(self, request: QueryRequest, context: QueryContext) -> QueryOutcome:
        started = time.perf_counter()
        generated = await self._generator.run(request, context)
        generation_ms = _elapsed_ms(started)
        stages = [
            QueryStageTrace(
                name="generation",
                status=(
                    "succeeded"
                    if generated.status == QueryStatus.PROCESSING
                    else generated.status
                ),
                duration_ms=generation_ms,
            )
        ]
        if generated.status != QueryStatus.PROCESSING or generated.sql is None:
            return replace(generated, stages=tuple(stages))

        validation_started = time.perf_counter()
        try:
            validated = self._validator.validate(generated.sql)
        except SQLValidationError as exc:
            stages.append(
                QueryStageTrace(
                    name="validation",
                    status="failed",
                    duration_ms=_elapsed_ms(validation_started),
                )
            )
            return replace(
                generated,
                status=QueryStatus.FAILED,
                error_code=exc.code,
                error_message=_validation_message(exc.code),
                stages=tuple(stages),
            )
        stages.append(
            QueryStageTrace(
                name="validation",
                status="succeeded",
                duration_ms=_elapsed_ms(validation_started),
            )
        )

        elapsed_ms = (time.perf_counter() - started) * 1_000
        remaining_ms = max(1, int(context.timeout_ms - elapsed_ms))
        execution_started = time.perf_counter()
        try:
            result = await self._executor.execute(validated, timeout_ms=remaining_ms)
        except QueryExecutionError as exc:
            stages.append(
                QueryStageTrace(
                    name="execution",
                    status="failed",
                    duration_ms=_elapsed_ms(execution_started),
                )
            )
            return replace(
                generated,
                status=QueryStatus.FAILED,
                sql=validated.sql,
                error_code=exc.code,
                error_message=_execution_message(exc.code),
                referenced_tables=validated.tables,
                referenced_columns=validated.columns,
                stages=tuple(stages),
            )

        stages.append(
            QueryStageTrace(
                name="execution",
                status="succeeded",
                duration_ms=result.duration_ms,
            )
        )
        return replace(
            generated,
            status=QueryStatus.SUCCEEDED,
            sql=validated.sql,
            columns=result.columns,
            rows=result.rows,
            truncated=result.truncated,
            execution_ms=result.duration_ms,
            referenced_tables=validated.tables,
            referenced_columns=validated.columns,
            stages=tuple(stages),
            summary=self._summary_builder.build(
                result.columns,
                result.rows,
                truncated=result.truncated,
            ),
        )

    async def close(self) -> None:
        """释放执行器持有的业务连接池。"""

        await self._executor.close()


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1_000, 2)


def _validation_message(code: QueryErrorCode) -> str:
    if code == QueryErrorCode.SQL_PARSE_ERROR:
        return "生成的 SQL 无法解析，请重试。"
    if code == QueryErrorCode.SQL_OUT_OF_SCOPE:
        return "生成的 SQL 使用了未授权的表或字段。"
    return "生成的 SQL 未通过安全校验。"


def _execution_message(code: QueryErrorCode) -> str:
    return {
        QueryErrorCode.EXECUTION_TIMEOUT: "查询执行超时，请缩小查询范围后重试。",
        QueryErrorCode.EXECUTION_BUSY: "查询服务繁忙，请稍后重试。",
        QueryErrorCode.EXECUTION_ERROR: "查询执行失败，请使用 trace_id 联系管理员。",
    }[code]
