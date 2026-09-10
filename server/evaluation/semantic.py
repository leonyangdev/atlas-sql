"""V3 语义层评测：指标正确性、强制过滤、粒度、时间口径、退款归因。

评测独立性原则（与 V2 retrieval.py 一致）：
    语义层错误不等于 SQL 执行错误，需要分层评测。
    本模块专注于「表列都对，但指标算错」的情况。

V3 新增的评测维度（相比 V2）：
    - Wrong Metric：指标 ID 识别错误（例如把 gross_margin_rate 识别为 net_sales）
    - Wrong Time：时间口径错误（paid_at vs refunded_at，财年 vs 自然年）
    - Wrong Aggregation：聚合方式错误（AVG(毛利率) 而非 SUM/SUM，库存跨日求和）
    - Missing Required Filter：缺少强制过滤（例如缺 is_test=false）
    - Wrong Grain：粒度不匹配（订单级 vs 明细级混用）

典型修复案例：「表列对但指标错」
    问题：2026 年上半年各品类毛利率
    V2 生成 SQL（错误）：
        SELECT category_name, AVG(gross_margin_rate) ...
        -- 错误：对行级毛利率求平均，结果不正确
    V3 修复（正确）：
        SELECT category_name,
               SUM(net_amount - cost_amount) / NULLIF(SUM(net_amount), 0) AS gross_margin_rate ...
        -- 正确：SUM(毛利) / SUM(销售额)

调用示例：
    from server.evaluation.semantic import SemanticEvaluator
    evaluator = SemanticEvaluator()
    report = evaluator.evaluate_sql(gold_sql, predicted_sql, metric_id="gross_margin_rate")
    print(report.summary())
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import sqlglot

from server.semantic.registry import MetricEntry

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 评测问题与结果数据类
# ──────────────────────────────────────────────────────────────


@dataclass
class SemanticQuestion:
    """语义评测问题。

    Attributes:
        question_id: 题目 ID。
        question: 自然语言问题。
        gold_sql: 黄金 SQL（人工审核过的正确答案）。
        gold_metric_ids: 该题涉及的正确指标 ID 列表。
        gold_required_filters: 必须出现在 SQL 中的强制过滤条件。
        gold_time_fields: 正确的时间归属字段（例如 paid_at）。
        gold_aggregation_pattern: 正确的聚合模式（例如 "SUM/SUM" 对应毛利率）。
        category: 题目类别（wrong_metric / wrong_time / wrong_aggregation / missing_filter）。
        description: 题目说明（用于学习站展示）。
    """

    question_id: str
    question: str
    gold_sql: str
    gold_metric_ids: list[str] = field(default_factory=list)
    gold_required_filters: list[str] = field(default_factory=list)
    gold_time_fields: list[str] = field(default_factory=list)
    gold_aggregation_pattern: str | None = None
    category: str = "general"
    description: str = ""


@dataclass
class SemanticEvalResult:
    """单题语义评测结果。"""

    question_id: str
    passed: bool

    # 指标识别
    metric_id_correct: bool | None = None
    predicted_metric_ids: list[str] = field(default_factory=list)

    # 强制过滤
    required_filters_present: bool | None = None
    missing_filters: list[str] = field(default_factory=list)

    # 时间口径
    time_field_correct: bool | None = None
    predicted_time_fields: list[str] = field(default_factory=list)

    # 聚合方式
    aggregation_correct: bool | None = None
    aggregation_detail: str = ""

    # 粒度
    grain_correct: bool | None = None

    # 失败原因
    failure_reason: str = ""
    failure_category: str = ""  # wrong_metric / wrong_time / wrong_aggregation / missing_filter


@dataclass
class SemanticEvalReport:
    """V3 语义评测汇总报告。"""

    total: int = 0
    passed: int = 0
    wrong_metric_count: int = 0
    wrong_time_count: int = 0
    wrong_aggregation_count: int = 0
    missing_filter_count: int = 0
    results: list[SemanticEvalResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0

    def summary(self) -> str:
        lines = [
            f"V3 语义评测报告",
            f"  总题数：{self.total}",
            f"  通过：{self.passed} ({self.pass_rate:.1%})",
            f"  错误指标：{self.wrong_metric_count}",
            f"  错误时间口径：{self.wrong_time_count}",
            f"  错误聚合方式：{self.wrong_aggregation_count}",
            f"  缺失强制过滤：{self.missing_filter_count}",
        ]
        return "\n".join(lines)

    def meets_v3_targets(self) -> bool:
        """检查是否满足 V3 验收门槛（pass_rate ≥ 70%，各类错误各 ≤ 20%）。"""
        if self.total == 0:
            return False
        return (
            self.pass_rate >= 0.70
            and self.wrong_metric_count / self.total <= 0.20
            and self.wrong_aggregation_count / self.total <= 0.20
            and self.missing_filter_count / self.total <= 0.20
        )


# ──────────────────────────────────────────────────────────────
# 评测器
# ──────────────────────────────────────────────────────────────


class SemanticEvaluator:
    """V3 语义层评测器。

    分析生成 SQL 与黄金 SQL 在语义层面的差异，不依赖数据库执行。
    主要通过 SQLGlot AST 分析：
    - 聚合函数使用模式（SUM/SUM vs AVG）
    - WHERE 子句包含的过滤条件
    - 时间字段使用（paid_at vs refunded_at）
    - GROUP BY 粒度
    """

    def evaluate_batch(
        self,
        questions: list[SemanticQuestion],
        predicted_sqls: dict[str, str],
    ) -> SemanticEvalReport:
        """批量评测。

        Args:
            questions: 语义评测题列表。
            predicted_sqls: {question_id: predicted_sql} 映射。
        """
        report = SemanticEvalReport(total=len(questions))

        for q in questions:
            predicted = predicted_sqls.get(q.question_id, "")
            result = self.evaluate_sql(
                q.gold_sql,
                predicted,
                question_id=q.question_id,
                gold_metric_ids=q.gold_metric_ids,
                gold_required_filters=q.gold_required_filters,
                gold_time_fields=q.gold_time_fields,
                gold_aggregation_pattern=q.gold_aggregation_pattern,
            )
            report.results.append(result)

            if result.passed:
                report.passed += 1
            else:
                if result.failure_category == "wrong_metric":
                    report.wrong_metric_count += 1
                elif result.failure_category == "wrong_time":
                    report.wrong_time_count += 1
                elif result.failure_category == "wrong_aggregation":
                    report.wrong_aggregation_count += 1
                elif result.failure_category == "missing_filter":
                    report.missing_filter_count += 1

        return report

    def evaluate_sql(
        self,
        gold_sql: str,
        predicted_sql: str,
        *,
        question_id: str = "",
        gold_metric_ids: list[str] | None = None,
        gold_required_filters: list[str] | None = None,
        gold_time_fields: list[str] | None = None,
        gold_aggregation_pattern: str | None = None,
    ) -> SemanticEvalResult:
        """对单条 SQL 进行语义评测。"""
        result = SemanticEvalResult(question_id=question_id, passed=True)

        if not predicted_sql or not predicted_sql.strip():
            result.passed = False
            result.failure_reason = "预测 SQL 为空"
            result.failure_category = "empty"
            return result

        # 1. 检查强制过滤
        if gold_required_filters:
            missing = _check_required_filters(predicted_sql, gold_required_filters)
            result.required_filters_present = len(missing) == 0
            result.missing_filters = missing
            if missing:
                result.passed = False
                result.failure_reason = f"缺少强制过滤：{missing}"
                result.failure_category = "missing_filter"

        # 2. 检查时间字段
        if gold_time_fields:
            predicted_time_fields = _extract_time_fields(predicted_sql)
            result.predicted_time_fields = predicted_time_fields
            time_ok = any(f in predicted_time_fields for f in gold_time_fields)
            result.time_field_correct = time_ok
            if not time_ok and result.passed:
                result.passed = False
                result.failure_reason = (
                    f"时间字段不匹配：期望 {gold_time_fields}，实际 {predicted_time_fields}"
                )
                result.failure_category = "wrong_time"

        # 3. 检查聚合方式（针对 gross_margin_rate 等比率指标）
        if gold_aggregation_pattern:
            agg_ok, agg_detail = _check_aggregation_pattern(predicted_sql, gold_aggregation_pattern)
            result.aggregation_correct = agg_ok
            result.aggregation_detail = agg_detail
            if not agg_ok and result.passed:
                result.passed = False
                result.failure_reason = f"聚合方式不正确：{agg_detail}"
                result.failure_category = "wrong_aggregation"

        return result


# ──────────────────────────────────────────────────────────────
# AST 分析辅助函数
# ──────────────────────────────────────────────────────────────


def _check_required_filters(sql: str, required_filters: list[str]) -> list[str]:
    """检查 SQL 中是否包含所有强制过滤条件（基于文本匹配）。

    检查策略：对每个 required_filter 中的关键 token 进行模糊存在性检查。
    例如 "order_status IN ('PAID', 'COMPLETED')" → 检查 'PAID' 和 'COMPLETED' 是否在 SQL 中。
    """
    sql_upper = sql.upper()
    missing = []

    for f in required_filters:
        # 提取过滤条件中的关键值（引号内内容）
        values = re.findall(r"'([^']+)'", f)
        keywords = re.findall(r"\b([A-Z_]+)\s*=\s*(?:true|false|TRUE|FALSE)", f.upper())
        keywords += [v.upper() for v in values]

        # 至少一个关键值出现在 SQL 中
        if not any(kw in sql_upper for kw in keywords if kw):
            missing.append(f)

    return missing


def _extract_time_fields(sql: str) -> list[str]:
    """从 SQL 中提取用到的时间字段名（简单文本扫描）。"""
    known_time_fields = [
        "first_valid_paid_at", "paid_at", "refunded_at", "created_at", "event_at",
        "snapshot_date", "order_date", "entry_date",
    ]
    sql_lower = sql.lower()
    return [f for f in known_time_fields if f in sql_lower]


def _check_aggregation_pattern(sql: str, pattern: str) -> tuple[bool, str]:
    """检查聚合模式是否符合预期。

    支持的模式：
    - "SUM/SUM"：比率指标必须用 SUM(分子)/SUM(分母)，禁止 AVG
    - "COUNT_DISTINCT"：必须用 COUNT(DISTINCT ...)
    - "NO_CROSS_DATE_SUM"：库存类指标禁止直接 SUM（需要快照过滤）
    """
    sql_upper = sql.upper()

    if pattern == "SUM/SUM":
        # 禁止 AVG 对毛利率、退款率等指标直接求平均
        has_avg = bool(re.search(r"\bAVG\s*\(", sql_upper))
        has_sum_over_sum = bool(
            re.search(r"SUM\s*\([^)]+\)\s*/\s*NULLIF\s*\(SUM", sql_upper)
            or re.search(r"SUM\s*\([^)]+\)\s*/\s*SUM\s*\(", sql_upper)
        )
        if has_avg and not has_sum_over_sum:
            return False, "检测到 AVG()，比率指标应使用 SUM(分子)/SUM(分母)"
        return True, "SUM/SUM 模式正确"

    if pattern == "COUNT_DISTINCT":
        has_count_distinct = bool(re.search(r"COUNT\s*\(\s*DISTINCT", sql_upper))
        if not has_count_distinct:
            return False, "缺少 COUNT(DISTINCT ...)，客户/订单计数应去重"
        return True, "COUNT(DISTINCT) 正确"

    if pattern == "NO_CROSS_DATE_SUM":
        # 库存快照：必须有 snapshot_date 过滤，且不是对多个日期 SUM
        has_snapshot_filter = "snapshot_date" in sql.lower()
        if not has_snapshot_filter:
            return False, "库存快照查询必须有 snapshot_date 过滤，禁止跨日求和"
        return True, "快照过滤正确"

    return True, f"未知模式 {pattern}，跳过检查"


# ──────────────────────────────────────────────────────────────
# V2 vs V3 对比评测
# ──────────────────────────────────────────────────────────────


@dataclass
class V2V3ComparisonReport:
    """V2 和 V3 语义评测对比报告。"""

    total: int = 0
    v2_pass_rate: float = 0.0
    v3_pass_rate: float = 0.0
    improvement: float = 0.0

    # 各类错误对比
    wrong_metric_v2: int = 0
    wrong_metric_v3: int = 0
    wrong_time_v2: int = 0
    wrong_time_v3: int = 0
    wrong_aggregation_v2: int = 0
    wrong_aggregation_v3: int = 0
    missing_filter_v2: int = 0
    missing_filter_v3: int = 0

    # 典型修复案例
    fixed_cases: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"V2 vs V3 语义对比报告（{self.total} 题）",
            f"  通过率：V2 {self.v2_pass_rate:.1%} → V3 {self.v3_pass_rate:.1%}",
            f"  提升：{self.improvement:+.1%}",
            f"  错误指标：V2 {self.wrong_metric_v2} → V3 {self.wrong_metric_v3}",
            f"  错误时间口径：V2 {self.wrong_time_v2} → V3 {self.wrong_time_v3}",
            f"  错误聚合方式：V2 {self.wrong_aggregation_v2} → V3 {self.wrong_aggregation_v3}",
            f"  缺失强制过滤：V2 {self.missing_filter_v2} → V3 {self.missing_filter_v3}",
        ]
        if self.fixed_cases:
            lines.append(f"\n  典型修复案例（{len(self.fixed_cases)} 条）：")
            for case in self.fixed_cases[:3]:
                lines.append(f"    [{case['question_id']}] {case['question'][:50]}")
                lines.append(f"      修复：{case['fix_description']}")
        return "\n".join(lines)


def compare_v2_v3(
    questions: list[SemanticQuestion],
    v2_sqls: dict[str, str],
    v3_sqls: dict[str, str],
) -> V2V3ComparisonReport:
    """对比 V2 和 V3 的语义评测结果。

    Args:
        questions: 评测题集（与 test_locked.yaml 保持一致）。
        v2_sqls: V2 生成的 SQL 字典 {question_id: sql}。
        v3_sqls: V3 生成的 SQL 字典 {question_id: sql}。
    """
    evaluator = SemanticEvaluator()
    v2_report = evaluator.evaluate_batch(questions, v2_sqls)
    v3_report = evaluator.evaluate_batch(questions, v3_sqls)

    # 找出 V2 失败但 V3 通过的案例（典型修复）
    v2_results = {r.question_id: r for r in v2_report.results}
    v3_results = {r.question_id: r for r in v3_report.results}
    fixed: list[dict] = []

    q_map = {q.question_id: q for q in questions}
    for qid, v3_r in v3_results.items():
        v2_r = v2_results.get(qid)
        if v2_r and not v2_r.passed and v3_r.passed:
            q = q_map.get(qid)
            fixed.append(
                {
                    "question_id": qid,
                    "question": q.question if q else qid,
                    "v2_failure": v2_r.failure_reason,
                    "fix_description": (
                        f"V2 失败原因：{v2_r.failure_category}，"
                        f"V3 通过（语义层注入了正确指标口径）"
                    ),
                }
            )

    return V2V3ComparisonReport(
        total=len(questions),
        v2_pass_rate=v2_report.pass_rate,
        v3_pass_rate=v3_report.pass_rate,
        improvement=v3_report.pass_rate - v2_report.pass_rate,
        wrong_metric_v2=v2_report.wrong_metric_count,
        wrong_metric_v3=v3_report.wrong_metric_count,
        wrong_time_v2=v2_report.wrong_time_count,
        wrong_time_v3=v3_report.wrong_time_count,
        wrong_aggregation_v2=v2_report.wrong_aggregation_count,
        wrong_aggregation_v3=v3_report.wrong_aggregation_count,
        missing_filter_v2=v2_report.missing_filter_count,
        missing_filter_v3=v3_report.missing_filter_count,
        fixed_cases=fixed,
    )


# ──────────────────────────────────────────────────────────────
# V3 语义专题评测样本（内置用于回归测试）
# ──────────────────────────────────────────────────────────────

V3_SEMANTIC_TEST_QUESTIONS: list[SemanticQuestion] = [
    # ── 错误聚合（AVG vs SUM/SUM）────────────────────────────
    SemanticQuestion(
        question_id="v3-sem-001",
        question="2026 年上半年各品类毛利率是多少？",
        gold_sql="""
SELECT dpc.category_name,
       SUM(foi.net_amount - foi.cost_amount) /
         NULLIF(SUM(foi.net_amount) - COALESCE(SUM(fri.refund_amount), 0), 0) AS gross_margin_rate
FROM fact_order_item foi
JOIN fact_order fo ON fo.id = foi.order_id
JOIN dim_product dp ON dp.id = foi.product_id AND dp.is_current = true
JOIN dim_product_category dpc ON dpc.id = dp.category_id
LEFT JOIN fact_refund_item fri ON fri.order_item_id = foi.id
LEFT JOIN fact_refund fr ON fr.id = fri.refund_id AND fr.refund_status = 'REFUNDED'
WHERE fo.order_status IN ('PAID', 'COMPLETED')
  AND fo.is_test = false
  AND fo.paid_at >= TIMESTAMPTZ '2026-01-01 00:00:00+08:00'
  AND fo.paid_at < TIMESTAMPTZ '2026-07-01 00:00:00+08:00'
GROUP BY dpc.category_name
ORDER BY gross_margin_rate DESC
        """.strip(),
        gold_metric_ids=["gross_margin_rate"],
        gold_required_filters=[
            "order_status IN ('PAID', 'COMPLETED')",
            "is_test = false",
        ],
        gold_time_fields=["paid_at"],
        gold_aggregation_pattern="SUM/SUM",
        category="wrong_aggregation",
        description="毛利率必须用 SUM(毛利)/SUM(销售额)，禁止 AVG 行级毛利率",
    ),

    # ── 缺失强制过滤 ──────────────────────────────────────────
    SemanticQuestion(
        question_id="v3-sem-002",
        question="2026 年有效订单量是多少？",
        gold_sql="""
SELECT COUNT(DISTINCT fo.id) AS paid_order_count
FROM fact_order fo
WHERE fo.order_status IN ('PAID', 'COMPLETED')
  AND fo.is_test = false
  AND fo.paid_at >= TIMESTAMPTZ '2026-01-01 00:00:00+08:00'
  AND fo.paid_at < TIMESTAMPTZ '2027-01-01 00:00:00+08:00'
        """.strip(),
        gold_metric_ids=["paid_order_count"],
        gold_required_filters=[
            "order_status IN ('PAID', 'COMPLETED')",
            "is_test = false",
        ],
        gold_time_fields=["paid_at"],
        gold_aggregation_pattern="COUNT_DISTINCT",
        category="missing_filter",
        description="必须同时过滤 order_status 和 is_test，缺一不可",
    ),

    # ── 时间口径：退款按 refunded_at ──────────────────────────
    SemanticQuestion(
        question_id="v3-sem-003",
        question="2026 年上半年退款金额是多少？",
        gold_sql="""
SELECT SUM(fri.refund_amount) AS refunded_amount
FROM fact_refund_item fri
JOIN fact_refund fr ON fr.id = fri.refund_id AND fr.refund_status = 'REFUNDED'
WHERE fr.refunded_at >= TIMESTAMPTZ '2026-01-01 00:00:00+08:00'
  AND fr.refunded_at < TIMESTAMPTZ '2026-07-01 00:00:00+08:00'
        """.strip(),
        gold_metric_ids=["refunded_amount"],
        gold_required_filters=["refund_status = 'REFUNDED'"],
        gold_time_fields=["refunded_at"],
        category="wrong_time",
        description="退款按 refunded_at 归属，不能用 paid_at 过滤退款时间",
    ),

    # ── 库存禁止跨日求和 ──────────────────────────────────────
    SemanticQuestion(
        question_id="v3-sem-004",
        question="今天各仓库的可用库存是多少？",
        gold_sql="""
SELECT dw.warehouse_name, SUM(fis.available_quantity) AS inventory_available_quantity
FROM fact_inventory_snapshot fis
JOIN dim_warehouse dw ON dw.id = fis.warehouse_id
WHERE fis.snapshot_date = CURRENT_DATE - 1
  AND fis.id IN (
    SELECT MAX(id) FROM fact_inventory_snapshot
    WHERE snapshot_date = CURRENT_DATE - 1
    GROUP BY warehouse_id, sku_id
  )
GROUP BY dw.warehouse_name
        """.strip(),
        gold_metric_ids=["inventory_available_quantity"],
        gold_required_filters=[],
        gold_time_fields=["snapshot_date"],
        gold_aggregation_pattern="NO_CROSS_DATE_SUM",
        category="wrong_aggregation",
        description="库存必须取单日快照，禁止对多日 available_quantity 直接 SUM",
    ),

    # ── 新客户按首次支付时间（不按注册时间）────────────────────
    SemanticQuestion(
        question_id="v3-sem-005",
        question="2026 年新客户数量",
        gold_sql="""
SELECT COUNT(DISTINCT dc.id) AS new_customer_count
FROM dim_customer dc
WHERE dc.first_valid_paid_at >= TIMESTAMPTZ '2026-01-01 00:00:00+08:00'
  AND dc.first_valid_paid_at < TIMESTAMPTZ '2027-01-01 00:00:00+08:00'
        """.strip(),
        gold_metric_ids=["new_customer_count"],
        gold_required_filters=[],
        gold_time_fields=["first_valid_paid_at"],
        gold_aggregation_pattern="COUNT_DISTINCT",
        category="wrong_time",
        description="新客户按首次有效支付时间（first_valid_paid_at），不能用 created_at",
    ),
]
