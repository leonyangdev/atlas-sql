"""V1 失败分类词表与可复现的初始归因规则。"""

from __future__ import annotations

import enum

from server.domain.query import QueryErrorCode, QueryResponse
from server.evaluation.benchmark_loader import BenchmarkQuestion


class FailureCategory(enum.StrEnum):
    WRONG_TABLE = "wrong_table"
    WRONG_COLUMN = "wrong_column"
    WRONG_JOIN = "wrong_join"
    WRONG_VALUE = "wrong_value"
    WRONG_METRIC = "wrong_metric"
    WRONG_TIME = "wrong_time"
    WRONG_AGGREGATION = "wrong_aggregation"
    SYNTAX_ERROR = "syntax_error"
    UNDETERMINED = "undetermined"


def suggest_failure_category(
    response: QueryResponse,
    question: BenchmarkQuestion,
) -> FailureCategory | None:
    """按可观察证据给出初始标签；人工可以在管理端覆盖。"""

    code = response.error.code if response.error else None
    if code == QueryErrorCode.SQL_PARSE_ERROR:
        return FailureCategory.SYNTAX_ERROR
    if code == QueryErrorCode.SQL_OUT_OF_SCOPE:
        generated_tables = set(response.referenced_tables)
        if generated_tables and generated_tables != set(question.required_tables):
            return FailureCategory.WRONG_TABLE
        return FailureCategory.WRONG_COLUMN
    if question.category == "join":
        return FailureCategory.WRONG_JOIN
    if question.category.startswith("time"):
        return FailureCategory.WRONG_TIME
    if question.category in {"value_mapping", "value"}:
        return FailureCategory.WRONG_VALUE
    if question.category in {"metric", "metric_semantics"}:
        return FailureCategory.WRONG_METRIC
    if question.category in {"aggregation", "top_n", "ranking"}:
        return FailureCategory.WRONG_AGGREGATION
    return FailureCategory.UNDETERMINED
