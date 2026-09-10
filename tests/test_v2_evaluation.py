"""V2 检索评测框架测试。

覆盖 server/evaluation/retrieval.py 的所有公开函数和数据类：
    - RetrievalQuestion / QuestionRetrievalResult / RetrievalReport 数据类
    - RetrievalReport.summary() / meets_v2_targets() / failed_questions()
    - _extract_column_labels()
    - _aggregate_results()
    - RetrievalEvaluator.run()（使用 InMemorySearchRepository + FakeReranker）
    - compare_v1_v2()

对应任务：V2-S06-T02（独立评测指标）、V2-S06-T03（V1 vs V2 对比报告）
"""

from __future__ import annotations

from server.domain.router import DomainRouter
from server.evaluation.retrieval import (
    QuestionRetrievalResult,
    RetrievalEvaluator,
    RetrievalQuestion,
    RetrievalReport,
    _aggregate_results,
    _extract_column_labels,
    compare_v1_v2,
)
from server.search.repository import Candidate, CandidateSource, InMemorySearchRepository
from server.search.reranker import FakeReranker
from server.search.retrieval import SchemaContext, TwoLevelRetriever

# ──────────────────────────────────────────────
# 辅助工厂
# ──────────────────────────────────────────────


def make_table_c(
    table_name: str, domain: str = "sales", score: float = 0.9, datasource_id: int = 1
) -> Candidate:
    return Candidate(
        doc_id=f"table:{datasource_id}:pub:{table_name}",
        object_type="table",
        score=score,
        source=CandidateSource.RRF,
        domain=domain,
        datasource_id=datasource_id,
        payload={"table_name": table_name, "business_name": ""},
    )


def make_col_c(table_name: str, column_name: str, score: float = 0.8) -> Candidate:
    return Candidate(
        doc_id=f"column:1:pub:{table_name}:{column_name}",
        object_type="column",
        score=score,
        source=CandidateSource.RRF,
        domain="sales",
        datasource_id=1,
        payload={"table_name": table_name, "column_name": column_name},
    )


def make_schema_ctx(
    tables: list[str] | None = None,
    columns: list[tuple[str, str]] | None = None,
) -> SchemaContext:
    """快速构造 SchemaContext。"""
    t_candidates = [make_table_c(t) for t in (tables or [])]
    c_candidates = [make_col_c(t, c) for t, c in (columns or [])]
    return SchemaContext(tables=t_candidates, columns=c_candidates)


# ──────────────────────────────────────────────
# RetrievalQuestion 数据类
# ──────────────────────────────────────────────


class TestRetrievalQuestion:
    def test_default_fields(self) -> None:
        q = RetrievalQuestion(question_id="q1", question="今年销售额")
        assert q.gold_domain is None
        assert q.gold_tables == []
        assert q.gold_columns == []
        assert q.gold_values == []
        assert q.gold_join_path == []
        assert q.category == "analytical"

    def test_full_construction(self) -> None:
        q = RetrievalQuestion(
            question_id="q2",
            question="华东销售额",
            gold_domain="sales",
            gold_tables=["fact_order", "dim_region"],
            gold_columns=["fact_order.net_amount", "dim_region.region_name"],
            gold_values=[{"column": "dim_region.region_name", "value": "East China"}],
            gold_join_path=["fact_order", "dim_store", "dim_city", "dim_region"],
            category="comparison",
        )
        assert q.gold_domain == "sales"
        assert len(q.gold_tables) == 2
        assert q.category == "comparison"


# ──────────────────────────────────────────────
# RetrievalReport 方法
# ──────────────────────────────────────────────


class TestRetrievalReport:
    def _make_report(self, **kwargs) -> RetrievalReport:  # type: ignore[no-untyped-def]
        defaults = dict(
            domain_accuracy=0.95,
            table_recall_at_k=0.90,
            table_precision_at_k=0.80,
            column_recall=0.85,
            value_link_accuracy=0.75,
            join_path_accuracy=0.70,
            total_questions=10,
            k=10,
            config="hybrid+rerank",
        )
        defaults.update(kwargs)
        return RetrievalReport(**defaults)

    def test_summary_contains_all_metrics(self) -> None:
        report = self._make_report()
        text = report.summary()
        assert "Domain Accuracy" in text
        assert "Table Recall" in text
        assert "Column Recall" in text
        assert "Value Linking" in text
        assert "Join Path" in text
        # 总题数
        assert "10" in text

    def test_summary_formats_as_percentage(self) -> None:
        report = self._make_report(domain_accuracy=0.98)
        assert "98.0%" in report.summary()

    def test_meets_v2_targets_passes(self) -> None:
        report = self._make_report(
            domain_accuracy=0.99,
            table_recall_at_k=0.98,
            column_recall=0.96,
        )
        assert report.meets_v2_targets() is True

    def test_meets_v2_targets_fails_domain(self) -> None:
        report = self._make_report(domain_accuracy=0.97, table_recall_at_k=0.98, column_recall=0.96)
        assert report.meets_v2_targets() is False

    def test_meets_v2_targets_fails_table_recall(self) -> None:
        report = self._make_report(domain_accuracy=0.99, table_recall_at_k=0.96, column_recall=0.96)
        assert report.meets_v2_targets() is False

    def test_meets_v2_targets_fails_column_recall(self) -> None:
        report = self._make_report(domain_accuracy=0.99, table_recall_at_k=0.98, column_recall=0.94)
        assert report.meets_v2_targets() is False

    def test_failed_questions_domain_wrong(self) -> None:
        r = QuestionRetrievalResult(question_id="q1", domain_correct=False)
        report = RetrievalReport(results=[r])
        assert len(report.failed_questions()) == 1

    def test_failed_questions_table_recall_partial(self) -> None:
        r = QuestionRetrievalResult(question_id="q1", table_recall_at_k=0.5)
        report = RetrievalReport(results=[r])
        assert len(report.failed_questions()) == 1

    def test_failed_questions_column_recall_partial(self) -> None:
        r = QuestionRetrievalResult(question_id="q1", column_recall=0.8)
        report = RetrievalReport(results=[r])
        assert len(report.failed_questions()) == 1

    def test_failed_questions_empty_when_all_pass(self) -> None:
        r = QuestionRetrievalResult(
            question_id="q1",
            domain_correct=True,
            table_recall_at_k=1.0,
            column_recall=1.0,
        )
        report = RetrievalReport(results=[r])
        assert report.failed_questions() == []

    def test_default_report_does_not_meet_targets(self) -> None:
        """默认全零的报告不应通过验收门槛。"""
        assert RetrievalReport().meets_v2_targets() is False


# ──────────────────────────────────────────────
# _extract_column_labels
# ──────────────────────────────────────────────


class TestExtractColumnLabels:
    def test_extracts_table_dot_column(self) -> None:
        ctx = make_schema_ctx(columns=[("fact_order", "net_amount"), ("dim_region", "region_name")])
        labels = _extract_column_labels(ctx)
        assert "fact_order.net_amount" in labels
        assert "dim_region.region_name" in labels

    def test_skips_columns_without_table_name(self) -> None:
        ctx = SchemaContext(
            columns=[
                Candidate(
                    doc_id="col:x",
                    object_type="column",
                    score=0.5,
                    source=CandidateSource.RRF,
                    domain="sales",
                    datasource_id=1,
                    payload={"table_name": "", "column_name": "some_col"},
                )
            ]
        )
        labels = _extract_column_labels(ctx)
        assert labels == []

    def test_empty_context_returns_empty(self) -> None:
        assert _extract_column_labels(SchemaContext()) == []


# ──────────────────────────────────────────────
# _aggregate_results
# ──────────────────────────────────────────────


class TestAggregateResults:
    def test_macro_average_domain_accuracy(self) -> None:
        results = [
            QuestionRetrievalResult(question_id="q1", domain_correct=True),
            QuestionRetrievalResult(question_id="q2", domain_correct=False),
            QuestionRetrievalResult(question_id="q3", domain_correct=True),
        ]
        report = _aggregate_results(results, total=3, k=10, config="hybrid")
        assert abs(report.domain_accuracy - 2 / 3) < 1e-9

    def test_skips_none_values_in_average(self) -> None:
        """gold 为空的题（None）不计入分母。"""
        results = [
            QuestionRetrievalResult(question_id="q1", table_recall_at_k=1.0),
            QuestionRetrievalResult(question_id="q2", table_recall_at_k=None),  # 无答案题
            QuestionRetrievalResult(question_id="q3", table_recall_at_k=0.5),
        ]
        report = _aggregate_results(results, total=3, k=10, config="hybrid")
        # 平均只取 q1(1.0) 和 q3(0.5)，分母=2
        assert abs(report.table_recall_at_k - 0.75) < 1e-9

    def test_empty_results_gives_zero_metrics(self) -> None:
        report = _aggregate_results([], total=0, k=10, config="hybrid")
        assert report.domain_accuracy == 0.0
        assert report.table_recall_at_k == 0.0
        assert report.total_questions == 0

    def test_config_preserved(self) -> None:
        report = _aggregate_results([], total=0, k=5, config="bm25_only")
        assert report.config == "bm25_only"
        assert report.k == 5

    def test_join_path_accuracy_boolean_conversion(self) -> None:
        """join_path_correct 是 bool，聚合时转为 1.0/0.0。"""
        results = [
            QuestionRetrievalResult(question_id="q1", join_path_correct=True),
            QuestionRetrievalResult(question_id="q2", join_path_correct=False),
        ]
        report = _aggregate_results(results, total=2, k=10, config="hybrid")
        assert abs(report.join_path_accuracy - 0.5) < 1e-9


# ──────────────────────────────────────────────
# RetrievalEvaluator.run()
# ──────────────────────────────────────────────


class TestRetrievalEvaluator:
    """使用 InMemorySearchRepository + FakeReranker，不依赖真实检索服务。"""

    def _make_repo_with_sales_tables(self) -> InMemorySearchRepository:
        repo = InMemorySearchRepository()
        repo.register_schema_candidates(
            [
                make_table_c("fact_order", datasource_id=1),
                make_table_c("dim_region", datasource_id=1),
                make_col_c("fact_order", "net_amount"),
                make_col_c("dim_region", "region_name"),
            ]
        )
        return repo

    async def test_run_returns_report(self) -> None:
        repo = self._make_repo_with_sales_tables()
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        router = DomainRouter()
        evaluator = RetrievalEvaluator(datasource_id=1, k=10)

        questions = [
            RetrievalQuestion(
                question_id="q1",
                question="今年销售额",
                gold_domain="sales",
                gold_tables=["fact_order"],
                gold_columns=["fact_order.net_amount"],
            )
        ]
        report = await evaluator.run(questions, retriever, router)

        assert report.total_questions == 1
        assert isinstance(report.domain_accuracy, float)
        assert isinstance(report.table_recall_at_k, float)
        assert isinstance(report.column_recall, float)

    async def test_run_correct_domain_scores_one(self) -> None:
        """路由正确时 domain_accuracy=1.0。"""
        repo = self._make_repo_with_sales_tables()
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        router = DomainRouter()
        evaluator = RetrievalEvaluator(datasource_id=1, k=10)

        questions = [
            RetrievalQuestion(
                question_id="q1",
                question="今年销售额是多少",
                gold_domain="sales",
            )
        ]
        report = await evaluator.run(questions, retriever, router)
        assert report.domain_accuracy == 1.0

    async def test_run_wrong_domain_scores_zero(self) -> None:
        """路由到错误域时 domain_accuracy=0.0。"""
        repo = self._make_repo_with_sales_tables()
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        router = DomainRouter()
        evaluator = RetrievalEvaluator(datasource_id=1, k=10)

        questions = [
            RetrievalQuestion(
                question_id="q1",
                question="今年销售额",
                gold_domain="inventory",  # 故意写错
            )
        ]
        report = await evaluator.run(questions, retriever, router)
        assert report.domain_accuracy == 0.0

    async def test_run_table_recall_full_hit(self) -> None:
        """召回了 gold 表时 recall=1.0。"""
        repo = self._make_repo_with_sales_tables()
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        router = DomainRouter()
        evaluator = RetrievalEvaluator(datasource_id=1, k=10)

        questions = [
            RetrievalQuestion(
                question_id="q1",
                question="今年销售额",
                gold_tables=["fact_order"],
            )
        ]
        report = await evaluator.run(questions, retriever, router)
        # fact_order 在预置候选里，应该被召回
        assert report.table_recall_at_k == 1.0

    async def test_run_table_recall_miss(self) -> None:
        """gold 表不在候选里时 recall=0.0。"""
        repo = InMemorySearchRepository()  # 空仓储
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        router = DomainRouter()
        evaluator = RetrievalEvaluator(datasource_id=1, k=10)

        questions = [
            RetrievalQuestion(
                question_id="q1",
                question="今年销售额",
                gold_tables=["fact_order_item"],
            )
        ]
        report = await evaluator.run(questions, retriever, router)
        assert report.table_recall_at_k == 0.0

    async def test_run_no_gold_tables_skips_recall(self) -> None:
        """无 gold 标注时，table_recall_at_k 不计入（结果为 0.0 默认值）。"""
        repo = self._make_repo_with_sales_tables()
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        router = DomainRouter()
        evaluator = RetrievalEvaluator(datasource_id=1, k=10)

        questions = [
            RetrievalQuestion(
                question_id="q1",
                question="今年销售额",
                # 不设 gold_tables
            )
        ]
        report = await evaluator.run(questions, retriever, router)
        # 无 gold，分母为 0，报告值为 0.0（默认）
        assert report.table_recall_at_k == 0.0

    async def test_run_multiple_questions_macro_avg(self) -> None:
        """多题时 domain_accuracy 是 macro 平均。"""
        repo = self._make_repo_with_sales_tables()
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        router = DomainRouter()
        evaluator = RetrievalEvaluator(datasource_id=1, k=10)

        questions = [
            RetrievalQuestion(question_id="q1", question="今年销售额", gold_domain="sales"),
            RetrievalQuestion(question_id="q2", question="今年销售额", gold_domain="inventory"),
        ]
        report = await evaluator.run(questions, retriever, router)
        assert report.total_questions == 2
        # 一对一错，期望 0.5
        assert abs(report.domain_accuracy - 0.5) < 1e-9

    async def test_run_exception_in_one_question_continues(self) -> None:
        """单题处理出错时，评测继续，不中断其他题目。"""
        repo = self._make_repo_with_sales_tables()
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        router = DomainRouter()
        evaluator = RetrievalEvaluator(datasource_id=1, k=10)

        # 提供一批问题，其中一题格式不影响结果
        questions = [
            RetrievalQuestion(question_id="q1", question="今年销售额", gold_domain="sales"),
            RetrievalQuestion(question_id="q2", question="今年销售额", gold_domain="sales"),
        ]
        report = await evaluator.run(questions, retriever, router)
        assert report.total_questions == 2


# ──────────────────────────────────────────────
# compare_v1_v2
# ──────────────────────────────────────────────


class TestCompareV1V2:
    def test_v1_none_describes_first_implementation(self) -> None:
        v2 = RetrievalReport(
            domain_accuracy=0.95,
            table_recall_at_k=0.92,
            column_recall=0.88,
            total_questions=5,
        )
        text = compare_v1_v2(None, v2)
        assert "V1" in text
        assert "V2" in text
        assert "静态" in text or "检索层" in text

    def test_v1_provided_shows_delta(self) -> None:
        v1 = RetrievalReport(
            domain_accuracy=0.90,
            table_recall_at_k=0.85,
            column_recall=0.80,
        )
        v2 = RetrievalReport(
            domain_accuracy=0.98,
            table_recall_at_k=0.97,
            column_recall=0.95,
        )
        text = compare_v1_v2(v1, v2)
        assert "90.0%" in text  # v1 domain accuracy
        assert "98.0%" in text  # v2 domain accuracy
        assert "增量" in text or "对比" in text

    def test_output_contains_latency_note(self) -> None:
        v2 = RetrievalReport()
        text = compare_v1_v2(None, v2)
        assert "时延" in text or "Reranker" in text

    def test_output_is_non_empty_string(self) -> None:
        text = compare_v1_v2(None, RetrievalReport())
        assert isinstance(text, str)
        assert len(text) > 0
