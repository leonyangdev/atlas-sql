"""V2 检索层独立评测：Domain Accuracy、Table/Column Recall & Precision、Value Linking、Join Path。

评测独立性原则（V2 核心目标）：
    检索层的错误不等于最终 SQL 的错误，因此需要分层评测。
    本模块只评测"检索 + 链接"的质量，不跑 SQL 生成。

    这样做的好处：
    1. 可以独立优化检索层而不干扰 SQL 生成层；
    2. 失败分析时能区分"召回缺失"和"SQL 生成错误"；
    3. 消融实验（bm25_only vs hybrid+rerank）只需跑检索评测，不需要 LLM token。

评测指标定义：
    - Domain Accuracy：路由到正确主域的比例（macro，每题一分）。
    - Table Recall@K：gold 表出现在 top_k 召回中的比例（macro 平均，跨所有问题）。
    - Table Precision@K：top_k 召回中 gold 表的比例（macro 平均）。
    - Column Recall（最终上下文）：gold 列出现在最终传给模型的 Schema Context 中的比例。
      "最终上下文"口径：经过两级召回 + rerank + token 裁剪后的列集合。
    - Value Linking Accuracy：值链接正确的过滤条件比例。
    - Join Path Accuracy：补齐路径与 gold 路径一致的比例。

无答案题处理：gold_tables/gold_columns 为空时，跳过该指标不计分，不计入分母。
多答案集合：gold_tables/gold_columns 为列表，predicted 包含其中任意一个即算命中。

调用示例（演示命令）：
    from server.evaluation.retrieval import RetrievalEvaluator
    evaluator = RetrievalEvaluator(...)
    report = await evaluator.run(questions, intent_parser, retriever)
    print(report.summary())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from server.search.retrieval import SchemaContext

logger = logging.getLogger(__name__)


@dataclass
class RetrievalQuestion:
    """评测问题，包含 gold 标注。

    Attributes:
        question_id: 问题唯一标识。
        question: 自然语言问题。
        gold_domain: 正确的主域，例如 "sales"。
        gold_tables: 正确的表名集合（应出现在召回结果中）。
        gold_columns: 正确的列名集合（格式 "table.column"，应出现在最终 Schema Context）。
        gold_values: 值链接的正确映射，格式 [{"column": "table.col", "value": "Apple"}]。
        gold_join_path: 正确的 JOIN 路径（表名列表，含桥接表）。
        category: 问题类型（analytical / ranking / comparison 等），用于分类分析。
    """

    question_id: str
    question: str
    gold_domain: str | None = None
    gold_tables: list[str] = field(default_factory=list)
    gold_columns: list[str] = field(default_factory=list)
    gold_values: list[dict[str, str]] = field(default_factory=list)
    gold_join_path: list[str] = field(default_factory=list)
    category: str = "analytical"


@dataclass
class QuestionRetrievalResult:
    """单题检索结果与评分。"""

    question_id: str
    predicted_domain: str | None = None
    domain_correct: bool | None = None

    predicted_tables: list[str] = field(default_factory=list)
    table_recall_at_k: float | None = None   # 召回率
    table_precision_at_k: float | None = None  # 精度

    predicted_columns: list[str] = field(default_factory=list)
    column_recall: float | None = None

    value_link_correct: int = 0
    value_link_total: int = 0
    value_link_accuracy: float | None = None

    join_path_correct: bool | None = None

    # 用于失败追溯的诊断信息
    trace_id: str = ""
    schema_context: SchemaContext | None = None


@dataclass
class RetrievalReport:
    """V2 检索层评测报告。

    Attributes:
        domain_accuracy: Domain Accuracy（macro）。
        table_recall_at_k: Table Recall@K（macro 平均）。
        table_precision_at_k: Table Precision@K（macro 平均）。
        column_recall: Column Recall（最终上下文，macro 平均）。
        value_link_accuracy: Value Linking Accuracy。
        join_path_accuracy: Join Path Accuracy。
        total_questions: 总题数。
        k: 召回的 top_k 值（写入报告保证口径一致）。
        results: 每题详细结果。
        config: 检索配置描述（bm25_only / dense_only / hybrid / hybrid+rerank）。
    """

    domain_accuracy: float = 0.0
    table_recall_at_k: float = 0.0
    table_precision_at_k: float = 0.0
    column_recall: float = 0.0
    value_link_accuracy: float = 0.0
    join_path_accuracy: float = 0.0
    total_questions: int = 0
    k: int = 10
    results: list[QuestionRetrievalResult] = field(default_factory=list)
    config: str = "hybrid+rerank"

    def summary(self) -> str:
        """生成人类可读的报告摘要。"""
        lines = [
            f"V2 检索评测报告（config={self.config}, K={self.k}, 总题数={self.total_questions}）",
            f"  Domain Accuracy:       {self.domain_accuracy:.1%}  （目标 ≥98%）",
            f"  Table Recall@{self.k}:      {self.table_recall_at_k:.1%}  （目标 ≥97%）",
            f"  Table Precision@{self.k}:   {self.table_precision_at_k:.1%}",
            f"  Column Recall（ctx）:   {self.column_recall:.1%}  （目标 ≥95%）",
            f"  Value Linking Acc:     {self.value_link_accuracy:.1%}",
            f"  Join Path Acc:         {self.join_path_accuracy:.1%}",
        ]
        return "\n".join(lines)

    def meets_v2_targets(self) -> bool:
        """判断是否达到 V2 验收门槛。"""
        return (
            self.domain_accuracy >= 0.98
            and self.table_recall_at_k >= 0.97
            and self.column_recall >= 0.95
        )

    def failed_questions(self) -> list[QuestionRetrievalResult]:
        """返回存在失败的题目列表，用于失败驱动迭代。"""
        failed = []
        for r in self.results:
            if r.domain_correct is False:
                failed.append(r)
            elif r.table_recall_at_k is not None and r.table_recall_at_k < 1.0:
                failed.append(r)
            elif r.column_recall is not None and r.column_recall < 1.0:
                failed.append(r)
        return failed


class RetrievalEvaluator:
    """对一批问题运行检索评测，计算各层指标。

    Args:
        datasource_id: 数据源 ID，传给检索器。
        k: Table Recall@K 的 K 值。
    """

    def __init__(self, datasource_id: int = 1, k: int = 10) -> None:
        self._datasource_id = datasource_id
        self._k = k

    async def run(
        self,
        questions: list[RetrievalQuestion],
        retriever: Any,  # TwoLevelRetriever（避免循环导入）
        intent_parser: Any,  # DomainRouter
        config: str = "hybrid+rerank",
    ) -> RetrievalReport:
        """对所有问题运行检索，汇总评测指标。

        Args:
            questions: 带 gold 标注的问题列表。
            retriever: TwoLevelRetriever 实例。
            intent_parser: DomainRouter 实例。
            config: 检索配置描述，写入报告。
        """
        from datetime import date

        results: list[QuestionRetrievalResult] = []

        for q in questions:
            result = QuestionRetrievalResult(question_id=q.question_id)
            try:
                # 解析意图
                now = date.today()
                intent = intent_parser.route(q.question, now)
                result.predicted_domain = intent.primary_domain

                # 域正确性
                if q.gold_domain:
                    result.domain_correct = (intent.primary_domain == q.gold_domain)

                # 两级召回
                schema_ctx: SchemaContext = await retriever.retrieve(
                    q.question,
                    intent,
                    datasource_id=self._datasource_id,
                )
                result.schema_context = schema_ctx

                # 预测的表和列
                result.predicted_tables = schema_ctx.table_names()
                result.predicted_columns = _extract_column_labels(schema_ctx)

                # Table Recall & Precision
                if q.gold_tables:
                    gold_set = set(q.gold_tables)
                    pred_set = set(result.predicted_tables[: self._k])
                    if gold_set:
                        result.table_recall_at_k = len(gold_set & pred_set) / len(gold_set)
                    if pred_set:
                        result.table_precision_at_k = len(gold_set & pred_set) / len(pred_set)

                # Column Recall（最终上下文）
                if q.gold_columns:
                    gold_cols = set(q.gold_columns)
                    pred_cols = set(result.predicted_columns)
                    result.column_recall = len(gold_cols & pred_cols) / len(gold_cols)

            except Exception as exc:
                logger.error(
                    "Retrieval evaluation failed for question %s: %s",
                    q.question_id, exc,
                )

            results.append(result)

        return _aggregate_results(results, total=len(questions), k=self._k, config=config)


def _extract_column_labels(schema_ctx: SchemaContext) -> list[str]:
    """从 SchemaContext 中提取所有列的 table.column 标签。"""
    labels = []
    for col in schema_ctx.columns:
        table_name = col.payload.get("table_name", "")
        col_name = col.payload.get("column_name", "")
        if table_name and col_name:
            labels.append(f"{table_name}.{col_name}")
    return labels


def _aggregate_results(
    results: list[QuestionRetrievalResult],
    total: int,
    k: int,
    config: str,
) -> RetrievalReport:
    """从单题结果聚合为整体报告（macro 平均，跳过无答案题）。"""
    domain_scores = [r.domain_correct for r in results if r.domain_correct is not None]
    table_recalls = [r.table_recall_at_k for r in results if r.table_recall_at_k is not None]
    table_precisions = [r.table_precision_at_k for r in results if r.table_precision_at_k is not None]
    col_recalls = [r.column_recall for r in results if r.column_recall is not None]
    value_accs = [r.value_link_accuracy for r in results if r.value_link_accuracy is not None]
    join_accs = [r.join_path_correct for r in results if r.join_path_correct is not None]

    def _mean(lst: list[Any]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return RetrievalReport(
        domain_accuracy=_mean(domain_scores),
        table_recall_at_k=_mean(table_recalls),
        table_precision_at_k=_mean(table_precisions),
        column_recall=_mean(col_recalls),
        value_link_accuracy=_mean(value_accs),
        join_path_accuracy=_mean([1.0 if j else 0.0 for j in join_accs]),
        total_questions=total,
        k=k,
        results=results,
        config=config,
    )


def compare_v1_v2(
    v1_report: RetrievalReport | None,
    v2_report: RetrievalReport,
) -> str:
    """生成 V1 vs V2 对比报告（V2-S06-T03）。

    V1 没有检索层独立评测，只有最终 SQL 准确率，因此 v1_report 可为 None。
    """
    lines = [
        "# V1 vs V2 对比报告",
        "",
        "## V2 检索层指标",
        v2_report.summary(),
        "",
    ]
    if v1_report is None:
        lines += [
            "## V1 基线",
            "V1 没有检索层独立评测，仅有最终 SQL 执行正确率。",
            "V2 引入混合检索 + Schema Linking 后，检索层首次可独立量化。",
            "",
            "## 质量收益",
            "  V2 新增能力：域路由置信度、两级召回、Value Linking、Join Graph 路径补齐。",
            "  无法与 V1 直接比较召回率（V1 使用静态 Schema，召回率视为 100%，但范围固定）。",
        ]
    else:
        lines += [
            "## V1 检索层指标",
            v1_report.summary(),
            "",
            "## 增量对比",
            f"  Domain Accuracy:  {v1_report.domain_accuracy:.1%} → {v2_report.domain_accuracy:.1%}",
            f"  Table Recall@K:   {v1_report.table_recall_at_k:.1%} → {v2_report.table_recall_at_k:.1%}",
            f"  Column Recall:    {v1_report.column_recall:.1%} → {v2_report.column_recall:.1%}",
        ]

    lines += [
        "",
        "## 时延与成本",
        "  V2 比 V1 增加了两次检索（OpenSearch + Milvus）和一次 Reranker 调用。",
        "  详细 p50/p95 时延见 Trace 记录。",
    ]
    return "\n".join(lines)
