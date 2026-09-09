"""V1-S03 SQL AST 校验、只读执行契约与完整链路测试。"""

from __future__ import annotations

import uuid

import pytest

from server.domain.query import QueryColumn, QueryErrorCode, QueryRequest, QueryStatus
from server.execution.postgres import (
    ExecutionErrorKind,
    ExecutionResult,
    QueryExecutionError,
)
from server.orchestrator.pipeline import SafeQueryPipeline
from server.orchestrator.query import QueryContext, QueryOutcome
from server.validation.sql import SQLValidationError, SQLValidator, ValidatedSQL


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS total FROM fact_order",
        """
        SELECT s.store_name, SUM(o.order_amount) AS amount
        FROM fact_order o JOIN dim_store s ON s.id = o.store_id
        WHERE o.is_test = false
        GROUP BY s.store_name
        ORDER BY amount DESC
        """,
        """
        WITH paid AS (
            SELECT store_id, SUM(order_amount) AS amount
            FROM fact_order GROUP BY store_id
        )
        SELECT p.amount FROM paid p
        """,
        """
        SELECT o.id FROM fact_order o
        WHERE EXISTS (
            SELECT 1 FROM fact_order_item i WHERE i.order_id = o.id
        )
        """,
    ],
)
def test_validator_accepts_read_only_queries(sql: str) -> None:
    result = SQLValidator().validate(sql)

    assert result.sql.startswith(("SELECT", "WITH"))
    assert result.tables


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM fact_order",
        "/* harmless-looking comment */ UPDATE fact_order SET is_test = true",
        "SELECT id FROM fact_order; DROP TABLE fact_order",
        "SELECT * INTO copied_orders FROM fact_order",
        "WITH changed AS (DELETE FROM fact_order RETURNING id) SELECT * FROM changed",
        "COPY fact_order TO '/tmp/orders.csv'",
    ],
)
def test_validator_rejects_write_and_multi_statement_sql(sql: str) -> None:
    with pytest.raises(SQLValidationError) as error:
        SQLValidator().validate(sql)

    assert error.value.code == QueryErrorCode.SQL_SECURITY_VIOLATION


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT quantity_on_hand FROM fact_inventory_snapshot",
        "SELECT order_no FROM fact_order",
        "SELECT private.fact_order.id FROM private.fact_order",
    ],
)
def test_validator_rejects_unknown_tables_columns_and_schema(sql: str) -> None:
    with pytest.raises(SQLValidationError) as error:
        SQLValidator().validate(sql)

    assert error.value.code == QueryErrorCode.SQL_OUT_OF_SCOPE


def test_validator_rejects_dangerous_or_unknown_function() -> None:
    with pytest.raises(SQLValidationError) as error:
        SQLValidator().validate("SELECT pg_sleep(10)")

    assert error.value.code == QueryErrorCode.SQL_SECURITY_VIOLATION


class StaticGenerator:
    model_version = "fake:sql-v1"

    def __init__(self, sql: str) -> None:
        self.sql = sql

    async def run(self, request: QueryRequest, context: QueryContext) -> QueryOutcome:
        return QueryOutcome(
            status=QueryStatus.PROCESSING,
            sql=self.sql,
            prompt_version="test-prompt",
            prompt_hash="a" * 64,
            model_version=self.model_version,
        )


class RecordingExecutor:
    def __init__(self, error: QueryExecutionError | None = None) -> None:
        self.calls: list[ValidatedSQL] = []
        self.error = error
        self.closed = False

    async def execute(self, query: ValidatedSQL, *, timeout_ms: int) -> ExecutionResult:
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        return ExecutionResult(
            columns=(QueryColumn(name="paid_order_count", data_type="int8"),),
            rows=((42,),),
            truncated=True,
            duration_ms=12.5,
        )

    async def close(self) -> None:
        self.closed = True


def make_context() -> QueryContext:
    return QueryContext(
        trace_id=uuid.uuid4(),
        identity="public",
        data_version="v0.1.0",
        schema_version="001",
        model_version="fake:sql-v1",
        timeout_ms=5_000,
        metric_ids=("paid_order_count",),
    )


@pytest.mark.asyncio
async def test_safe_pipeline_executes_only_after_validation() -> None:
    executor = RecordingExecutor()
    pipeline = SafeQueryPipeline(
        StaticGenerator("SELECT COUNT(*) AS paid_order_count FROM fact_order"),
        SQLValidator(),
        executor,
    )

    result = await pipeline.run(QueryRequest(question="订单量"), make_context())

    assert result.status == QueryStatus.SUCCEEDED
    assert result.rows == ((42,),)
    assert result.truncated is True
    assert result.execution_ms == 12.5
    assert result.referenced_tables == ("fact_order",)
    assert [stage.name for stage in result.stages] == ["generation", "validation", "execution"]
    assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_invalid_sql_never_reaches_executor() -> None:
    executor = RecordingExecutor()
    pipeline = SafeQueryPipeline(
        StaticGenerator("SELECT pg_sleep(10)"),
        SQLValidator(),
        executor,
    )

    result = await pipeline.run(QueryRequest(question="订单量"), make_context())

    assert result.status == QueryStatus.FAILED
    assert result.error_code == QueryErrorCode.SQL_SECURITY_VIOLATION
    assert executor.calls == []


@pytest.mark.asyncio
async def test_execution_timeout_is_typed_and_keeps_candidate_sql() -> None:
    executor = RecordingExecutor(QueryExecutionError(ExecutionErrorKind.TIMEOUT))
    pipeline = SafeQueryPipeline(
        StaticGenerator("SELECT id FROM fact_order"),
        SQLValidator(),
        executor,
    )

    result = await pipeline.run(QueryRequest(question="订单"), make_context())

    assert result.status == QueryStatus.FAILED
    assert result.error_code == QueryErrorCode.EXECUTION_TIMEOUT
    assert result.sql == "SELECT id FROM fact_order"
    assert result.stages[-1].status == "failed"


@pytest.mark.asyncio
async def test_pipeline_closes_executor() -> None:
    executor = RecordingExecutor()
    pipeline = SafeQueryPipeline(StaticGenerator("SELECT 1"), SQLValidator(), executor)

    await pipeline.close()

    assert executor.closed is True
