"""V1-S04 结果摘要与 V1-S05 基线评测测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from server.api.app import create_app
from server.domain.query import (
    QueryColumn,
    QueryResponse,
    QueryStageTrace,
    QueryStatus,
    QueryTrace,
)
from server.evaluation.baseline import BaselineEvaluator, select_v1_cases
from server.evaluation.benchmark_loader import BenchmarkQuestion, load_split
from server.generation.answer import ResultSummaryBuilder
from server.observability.failure import FailureCategory
from server.validation.sql import SQLValidator
from tests.test_config import valid_settings

BENCHMARK = Path(__file__).resolve().parents[1] / "benchmarks" / "v1" / "test.yaml"


def test_summary_distinguishes_empty_result_from_zero() -> None:
    builder = ResultSummaryBuilder()
    column = (QueryColumn(name="sales_amount", data_type="numeric"),)

    empty = builder.build(column, (), truncated=False)
    zero = builder.build(column, (("0.00",),), truncated=False)

    assert empty == "未查询到符合条件的记录。"
    assert "0.00" in zero
    assert empty != zero


def test_summary_uses_only_returned_shape_and_values() -> None:
    summary = ResultSummaryBuilder().build(
        (QueryColumn(name="amount", data_type="numeric"),),
        (("123456789012345678.99",),),
        truncated=False,
    )

    assert "123456789012345678.99" in summary


def test_v1_case_selection_is_fixed_by_ast_scope() -> None:
    split = load_split(BENCHMARK)
    selected = select_v1_cases(split.questions, SQLValidator())
    ids = {question.id for question in selected}

    assert len(selected) == 19
    assert "test-001" in ids
    assert "test-003" not in ids  # 库存表不属于冻结 Sales 范围
    assert "test-025" in ids  # 澄清题仍是用户链路的一部分


def response_for(question: str, rows: list[list[str]]) -> QueryResponse:
    now = datetime.now(UTC)
    trace_id = uuid4()
    return QueryResponse(
        question=question,
        session_id="benchmark",
        trace_id=trace_id,
        status=QueryStatus.SUCCEEDED,
        sql="SELECT COUNT(*) AS active_store_count FROM dim_store WHERE is_current = TRUE",
        columns=[QueryColumn(name="active_store_count", data_type="int8")],
        rows=rows,
        summary="查询结果。",
        referenced_tables=["dim_store"],
        trace=QueryTrace(
            trace_id=trace_id,
            identity="public",
            status=QueryStatus.SUCCEEDED,
            data_version="v0.1.0",
            schema_version="001",
            model_version="fake:sql-v1",
            timeout_ms=5_000,
            prompt_version="v1-sql-generation-001",
            total_tokens=100,
            stages=[
                QueryStageTrace(name="validation", status="succeeded", duration_ms=1),
                QueryStageTrace(name="execution", status="succeeded", duration_ms=2),
            ],
            created_at=now,
            updated_at=now,
        ),
    )


@pytest.mark.asyncio
async def test_baseline_report_has_denominators_latency_and_tokens() -> None:
    question = load_split(BENCHMARK).questions[0]

    async def submit(text: str, identity: str) -> QueryResponse:
        return response_for(text, [["4"]])

    async def gold(_question: BenchmarkQuestion) -> list[tuple[str]]:
        return [("4",)]

    report = await BaselineEvaluator(submit, gold).run([question], environment="test")

    assert report.sample_count == 1
    assert report.sql_case_count == 1
    assert report.metrics["syntax_valid_rate"] == 1.0
    assert report.metrics["execution_correct_rate"] == 1.0
    assert report.metrics["first_success_rate"] == 1.0
    assert report.metrics["total_tokens"] == 100
    assert report.failure_counts == {}


def test_failure_categories_include_required_manual_label() -> None:
    assert FailureCategory("undetermined") == FailureCategory.UNDETERMINED
    assert {item.value for item in FailureCategory} >= {
        "wrong_table", "wrong_column", "wrong_join", "wrong_value", "wrong_metric",
        "wrong_time", "wrong_aggregation", "syntax_error", "undetermined",
    }


@pytest.mark.asyncio
async def test_trace_admin_api_is_closed_without_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ATLAS_ADMIN_TOKEN", raising=False)
    app = create_app(valid_settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/admin/traces")

    assert response.status_code == 503
