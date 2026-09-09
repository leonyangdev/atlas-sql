"""V1 基线评测聚合器。

评测只保存题号、候选 SQL、行数、是否正确和失败类别，不把完整业务结果写入报告。测试集
筛选逻辑只依据冻结白名单与 Gold SQL 可校验性，不读取题目来调整 Prompt。
"""

from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from server.domain.query import QueryResponse, QueryStatus
from server.evaluation.benchmark_loader import BenchmarkQuestion
from server.evaluation.comparator import ResultSet, compare_action, compare_results
from server.observability.failure import suggest_failure_category
from server.validation.sql import SQLValidationError, SQLValidator

SubmitQuery = Callable[[str, str], Awaitable[QueryResponse]]
ExecuteGold = Callable[[BenchmarkQuestion], Awaitable[ResultSet]]


@dataclass(frozen=True)
class BaselineCaseResult:
    question_id: str
    category: str
    status: str
    trace_id: str
    candidate_sql: str | None
    syntax_valid: bool | None
    execution_correct: bool | None
    first_success: bool
    latency_ms: float
    total_tokens: int
    failure_category: str | None
    failure_reason: str | None


@dataclass(frozen=True)
class BaselineReport:
    dataset_version: str
    schema_version: str
    split: str
    environment: str
    model_version: str
    prompt_version: str | None
    sample_count: int
    sql_case_count: int
    metrics: dict[str, int | float | None]
    failure_counts: dict[str, int]
    cases: tuple[BaselineCaseResult, ...]

    def to_dict(self) -> dict[str, object]:
        """转换成可直接 JSON 序列化的报告。"""

        return asdict(self)


def select_v1_cases(
    questions: Sequence[BenchmarkQuestion],
    validator: SQLValidator,
) -> list[BenchmarkQuestion]:
    """选择固定 Sales 白名单可表达的 SQL 题，以及显式拒绝/澄清题。"""

    selected: list[BenchmarkQuestion] = []
    for question in questions:
        if question.expected_action is not None:
            selected.append(question)
            continue
        if question.gold_sql is None:
            continue
        try:
            validator.validate(question.gold_sql)
        except SQLValidationError:
            continue
        selected.append(question)
    return selected


class BaselineEvaluator:
    """逐题执行一次模型链路和 Gold 查询并聚合真实指标。"""

    def __init__(self, submit: SubmitQuery, execute_gold: ExecuteGold) -> None:
        self._submit = submit
        self._execute_gold = execute_gold

    async def run(
        self,
        questions: Sequence[BenchmarkQuestion],
        *,
        environment: str,
    ) -> BaselineReport:
        cases: list[BaselineCaseResult] = []
        model_version = "unknown"
        prompt_version: str | None = None
        for question in questions:
            started = time.perf_counter()
            response = await self._submit(question.question, question.identity)
            latency_ms = round((time.perf_counter() - started) * 1_000, 2)
            model_version = response.trace.model_version
            prompt_version = response.trace.prompt_version or prompt_version
            cases.append(await self._evaluate_case(question, response, latency_ms))

        first = questions[0] if questions else None
        return BaselineReport(
            dataset_version=first.dataset_version if first else "unknown",
            schema_version=first.schema_version if first else "unknown",
            split=first.split if first else "test",
            environment=environment,
            model_version=model_version,
            prompt_version=prompt_version,
            sample_count=len(cases),
            sql_case_count=sum(case.syntax_valid is not None for case in cases),
            metrics=_metrics(cases),
            failure_counts=dict(
                sorted(
                    Counter(
                        case.failure_category for case in cases if case.failure_category
                    ).items()
                )
            ),
            cases=tuple(cases),
        )

    async def _evaluate_case(
        self,
        question: BenchmarkQuestion,
        response: QueryResponse,
        latency_ms: float,
    ) -> BaselineCaseResult:
        syntax_valid: bool | None = None
        execution_correct: bool | None = None
        matched = False
        reason = ""
        if question.expected_action is not None:
            actual = _actual_action(response.status)
            comparison = compare_action(question.id, question.expected_action, actual)
            matched, reason = comparison.matched, comparison.reason
        else:
            syntax_valid = any(
                stage.name == "validation" and stage.status == "succeeded"
                for stage in response.trace.stages
            )
            if response.status == QueryStatus.SUCCEEDED:
                gold = await self._execute_gold(question)
                predicted: ResultSet = [tuple(row) for row in response.rows]
                gold, predicted = _normalize_numeric_columns(
                    gold,
                    predicted,
                    [column.data_type for column in response.columns],
                )
                comparison = compare_results(
                    question.id,
                    gold,
                    predicted,
                    is_ordered=question.is_ordered,
                )
                execution_correct = comparison.matched
                matched, reason = comparison.matched, comparison.reason
            else:
                execution_correct = False
                reason = response.error.code.value if response.error else response.status.value

        category = None if matched else suggest_failure_category(response, question)
        return BaselineCaseResult(
            question_id=question.id,
            category=question.category,
            status=response.status.value,
            trace_id=str(response.trace_id),
            candidate_sql=response.sql,
            syntax_valid=syntax_valid,
            execution_correct=execution_correct,
            first_success=matched,
            latency_ms=latency_ms,
            total_tokens=response.trace.total_tokens,
            failure_category=category.value if category else None,
            failure_reason=reason or None,
        )


def _actual_action(status: QueryStatus) -> str:
    if status == QueryStatus.REJECTED:
        return "reject"
    if status == QueryStatus.CLARIFICATION_REQUIRED:
        return "clarify"
    return "generate"


def _normalize_numeric_columns(
    gold: ResultSet,
    predicted: ResultSet,
    data_types: Sequence[str],
) -> tuple[ResultSet, ResultSet]:
    """按数据库列类型恢复 Decimal，避免仅因显示小数位不同判为错误。"""

    numeric_indexes = {
        index
        for index, data_type in enumerate(data_types)
        if any(token in data_type.lower() for token in ("numeric", "decimal", "float"))
    }

    def normalize(rows: ResultSet) -> ResultSet:
        normalized: ResultSet = []
        for row in rows:
            cells = list(row)
            for index in numeric_indexes:
                if index >= len(cells) or cells[index] is None:
                    continue
                try:
                    cells[index] = Decimal(str(cells[index]))
                except InvalidOperation:
                    pass
            normalized.append(tuple(cells))
        return normalized

    return normalize(gold), normalize(predicted)


def _metrics(cases: Sequence[BaselineCaseResult]) -> dict[str, int | float | None]:
    sql_cases = [case for case in cases if case.syntax_valid is not None]
    latencies = sorted(case.latency_ms for case in cases)
    total_tokens = sum(case.total_tokens for case in cases)
    return {
        "syntax_valid_rate": _rate(
            sum(case.syntax_valid is True for case in sql_cases), len(sql_cases)
        ),
        "execution_correct_rate": _rate(
            sum(case.execution_correct is True for case in sql_cases), len(sql_cases)
        ),
        "first_success_rate": _rate(sum(case.first_success for case in cases), len(cases)),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "total_tokens": total_tokens,
        "average_tokens": round(total_tokens / len(cases), 2) if cases else None,
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    index = max(0, math.ceil(len(values) * percentile) - 1)
    return round(values[index], 2)
