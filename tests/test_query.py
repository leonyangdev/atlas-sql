"""V1-S01 问数契约、固定范围和编排器测试。"""

from __future__ import annotations

import uuid

import httpx
import pytest
from pydantic import ValidationError

from datasets.schema.catalog import TABLES
from server.api.app import create_app
from server.domain.query import (
    MAX_QUESTION_LENGTH,
    QueryColumn,
    QueryErrorCode,
    QueryRequest,
    QueryStatus,
)
from server.domain.sales_scope import ALLOWED_COLUMNS, assess_sales_scope, is_allowed_column
from server.orchestrator.query import QueryContext, QueryOrchestrator, QueryOutcome, QueryPipeline
from server.query.repository import InMemoryQueryRepository
from tests.test_config import valid_settings


def make_orchestrator(
    repository: InMemoryQueryRepository,
    pipeline: QueryPipeline | None = None,
) -> QueryOrchestrator:
    """使用固定版本创建离线编排器。"""

    return QueryOrchestrator(
        repository,
        data_version="v0.1.0",
        schema_version="001",
        model_version="fake-v1",
        timeout_ms=5_000,
        pipeline=pipeline,
    )


def test_query_request_normalizes_question_and_creates_session() -> None:
    request = QueryRequest(question="  今年销售额  ")

    assert request.question == "今年销售额"
    assert request.session_id
    assert request.trace_id is None


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_query_request_rejects_blank_question(question: str) -> None:
    with pytest.raises(ValidationError):
        QueryRequest(question=question)


def test_query_request_rejects_overlong_question() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(question="销" * (MAX_QUESTION_LENGTH + 1))


def test_sales_scope_is_frozen_to_fifteen_existing_tables() -> None:
    catalog = {table.name: table for table in TABLES}

    assert len(ALLOWED_COLUMNS) == 15
    assert set(ALLOWED_COLUMNS) <= set(catalog)
    for table_name, allowed_columns in ALLOWED_COLUMNS.items():
        catalog_columns = {column.name for column in catalog[table_name].columns}
        assert allowed_columns <= catalog_columns


def test_sales_scope_excludes_unknown_and_confidential_fields() -> None:
    assert is_allowed_column("fact_order", "net_amount") is False
    assert is_allowed_column("unknown_table", "id") is False
    assert is_allowed_column("fact_order", "order_no") is False
    assert is_allowed_column("fact_order", "tenant_id") is False


def test_sales_scope_recognizes_metric_draft() -> None:
    decision = assess_sales_scope("今年华北区的净销售额是多少？")

    assert decision.status == QueryStatus.PROCESSING
    assert decision.metric_ids == ("net_sales",)


def test_sales_scope_rejects_inventory_question() -> None:
    decision = assess_sales_scope("查询各仓库的可用库存")

    assert decision.status == QueryStatus.REJECTED
    assert decision.error_code == QueryErrorCode.OUT_OF_SCOPE


def test_sales_scope_requires_clarification_for_income() -> None:
    decision = assess_sales_scope("今年收入是多少？")

    assert decision.status == QueryStatus.CLARIFICATION_REQUIRED
    assert decision.error_code == QueryErrorCode.AMBIGUOUS_METRIC


class CapturingPipeline:
    """记录编排器传入的请求上下文，并返回确定性成功结果。"""

    request: QueryRequest | None = None
    context: QueryContext | None = None

    async def run(self, request: QueryRequest, context: QueryContext) -> QueryOutcome:
        self.request = request
        self.context = context
        return QueryOutcome(
            status=QueryStatus.SUCCEEDED,
            sql="SELECT 1 AS answer",
            columns=(QueryColumn(name="answer", data_type="integer"),),
            rows=((1,),),
        )


@pytest.mark.asyncio
async def test_orchestrator_passes_identity_versions_and_budget() -> None:
    repository = InMemoryQueryRepository()
    pipeline = CapturingPipeline()
    orchestrator = make_orchestrator(repository, pipeline)
    trace_id = uuid.uuid4()
    request = QueryRequest(question="今年销售额", session_id="session-1", trace_id=trace_id)

    response = await orchestrator.submit(request, identity="analyst_north")

    assert response.status == QueryStatus.SUCCEEDED
    assert response.sql == "SELECT 1 AS answer"
    assert response.rows == [[1]]
    assert pipeline.context == QueryContext(
        trace_id=trace_id,
        identity="analyst_north",
        data_version="v0.1.0",
        schema_version="001",
        model_version="fake-v1",
        timeout_ms=5_000,
        metric_ids=("net_sales",),
    )
    assert repository.records[trace_id].status == QueryStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_orchestrator_rejects_out_of_scope_before_pipeline() -> None:
    repository = InMemoryQueryRepository()
    pipeline = CapturingPipeline()
    orchestrator = make_orchestrator(repository, pipeline)

    response = await orchestrator.submit(QueryRequest(question="库存还有多少？"), "public")

    assert response.status == QueryStatus.REJECTED
    assert response.error is not None
    assert response.error.code == QueryErrorCode.OUT_OF_SCOPE
    assert pipeline.request is None
    assert repository.records[response.trace_id].status == QueryStatus.REJECTED


class FailingPipeline:
    async def run(self, request: QueryRequest, context: QueryContext) -> QueryOutcome:
        raise RuntimeError("postgresql://admin:secret@private-host/business")


@pytest.mark.asyncio
async def test_orchestrator_does_not_expose_internal_exception() -> None:
    repository = InMemoryQueryRepository()
    orchestrator = make_orchestrator(repository, FailingPipeline())

    response = await orchestrator.submit(QueryRequest(question="订单量是多少？"), "public")

    assert response.status == QueryStatus.FAILED
    assert response.error is not None
    assert response.error.code == QueryErrorCode.INTERNAL_ERROR
    assert "secret" not in response.error.message
    assert "private-host" not in response.error.message


class FailingRepository(InMemoryQueryRepository):
    async def create(self, state: object) -> None:
        raise RuntimeError("control database password=secret")


@pytest.mark.asyncio
async def test_orchestrator_does_not_expose_repository_exception() -> None:
    orchestrator = make_orchestrator(FailingRepository())

    response = await orchestrator.submit(QueryRequest(question="订单量是多少？"), "public")

    assert response.status == QueryStatus.FAILED
    assert response.error is not None
    assert response.error.code == QueryErrorCode.INTERNAL_ERROR
    assert "secret" not in response.error.message


@pytest.mark.asyncio
async def test_orchestrator_without_pipeline_keeps_processing_state() -> None:
    repository = InMemoryQueryRepository()
    orchestrator = make_orchestrator(repository)

    response = await orchestrator.submit(QueryRequest(question="订单量是多少？"), "public")

    assert response.status == QueryStatus.PROCESSING
    assert response.sql is None
    assert response.columns == []
    assert response.rows == []


@pytest.mark.asyncio
async def test_query_api_returns_processing_and_can_read_own_trace() -> None:
    repository = InMemoryQueryRepository()
    orchestrator = make_orchestrator(repository)
    app = create_app(valid_settings(), query_orchestrator=orchestrator)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        submitted = await client.post(
            "/api/v1/query",
            json={"question": "今年销售额", "session_id": "web-session"},
            headers={"x-atlas-identity": "analyst_north"},
        )
        trace_id = submitted.json()["trace_id"]
        fetched = await client.get(
            f"/api/v1/query/{trace_id}",
            headers={"x-atlas-identity": "analyst_north"},
        )
        hidden = await client.get(
            f"/api/v1/query/{trace_id}",
            headers={"x-atlas-identity": "someone_else"},
        )

    assert submitted.status_code == 202
    assert submitted.json()["status"] == "processing"
    assert fetched.status_code == 200
    assert fetched.json()["trace"]["identity"] == "analyst_north"
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_query_api_rejects_invalid_question_and_out_of_scope_domain() -> None:
    repository = InMemoryQueryRepository()
    orchestrator = make_orchestrator(repository)
    app = create_app(valid_settings(), query_orchestrator=orchestrator)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        blank = await client.post("/api/v1/query", json={"question": "   "})
        overlong = await client.post(
            "/api/v1/query", json={"question": "销" * (MAX_QUESTION_LENGTH + 1)}
        )
        inventory = await client.post("/api/v1/query", json={"question": "查询库存"})

    assert blank.status_code == 422
    assert overlong.status_code == 422
    assert inventory.status_code == 200
    assert inventory.json()["status"] == "rejected"
    assert inventory.json()["error"]["code"] == "out_of_scope"
