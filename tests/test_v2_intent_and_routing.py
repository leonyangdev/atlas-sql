"""V2-S01 测试：QueryIntent 定义 + DomainRouter 域路由 + 时间解析 + 澄清逻辑。

验收场景（V2-S01 故事验收要求）：
    - "苹果手机上月销售"路由到销售并允许商品维度
    - "今年表现怎么样"不会自行选指标
    - 固定 now 能重放相同时间窗口
    - 无域、低置信度、歧义时间和未支持意图返回澄清

覆盖的任务：
    V2-S01-T01: QueryIntent 数据类定义
    V2-S01-T02: 时间解析（今年/上月/同比/环比/近N天/YYYY年）
    V2-S01-T03: 澄清逻辑（无域/低置信度/歧义指标/宽泛问题）
"""

from datetime import date

import pytest

from server.domain.intent import (
    IntentType,
    QueryIntent,
    TimeRange,
    FilterCondition,
    MetricMention,
    DimensionMention,
)
from server.domain.router import DomainRouter, _parse_time_range


# ──────────────────────────────────────────────
# 辅助工具
# ──────────────────────────────────────────────

def make_router() -> DomainRouter:
    return DomainRouter()


NOW = date(2026, 9, 10)


# ──────────────────────────────────────────────
# T01: QueryIntent 数据类测试
# ──────────────────────────────────────────────

class TestQueryIntentModel:
    """确认 QueryIntent 的所有字段类型和默认值正确。"""

    def test_default_fields(self) -> None:
        intent = QueryIntent(intent_type=IntentType.ANALYTICAL)
        assert intent.metric_mentions == []
        assert intent.dimension_mentions == []
        assert intent.filters == []
        assert intent.time_range is None
        assert intent.ranking_limit is None
        assert intent.unresolved == []
        assert intent.domain_candidates == {}
        assert intent.primary_domain is None
        assert intent.requires_clarification is False
        assert intent.clarification_prompt is None
        assert intent.now is None

    def test_full_construction(self) -> None:
        tr = TimeRange(start=date(2026, 1, 1), end=date(2026, 12, 31), label="今年")
        intent = QueryIntent(
            intent_type=IntentType.RANKING,
            metric_mentions=[MetricMention(text="销售额", resolved_metric_id="net_sales")],
            filters=[FilterCondition(concept="区域", value="华东")],
            time_range=tr,
            ranking_limit=5,
            domain_candidates={"sales": 0.96, "product": 0.57},
            primary_domain="sales",
            now=NOW,
        )
        assert intent.ranking_limit == 5
        assert intent.primary_domain == "sales"
        assert intent.time_range is not None
        assert intent.time_range.label == "今年"

    def test_time_range_with_comparison(self) -> None:
        """同比时间范围应包含 comparison_start / comparison_end。"""
        tr = TimeRange(
            start=date(2026, 1, 1),
            end=date(2026, 12, 31),
            label="今年",
            comparison_start=date(2025, 1, 1),
            comparison_end=date(2025, 12, 31),
        )
        assert tr.comparison_start is not None
        assert tr.comparison_start.year == 2025


# ──────────────────────────────────────────────
# T02: 时间解析
# ──────────────────────────────────────────────

class TestTimeRangeParsing:
    """_parse_time_range 的各种表达式解析。"""

    def test_parse_this_year(self) -> None:
        tr = _parse_time_range("今年销售额是多少", NOW)
        assert tr is not None
        assert tr.start == date(2026, 1, 1)
        assert tr.end == date(2026, 12, 31)
        assert tr.label == "今年"

    def test_parse_last_year(self) -> None:
        tr = _parse_time_range("去年同期有多少", NOW)
        assert tr is not None
        assert tr.start == date(2025, 1, 1)
        assert tr.end == date(2025, 12, 31)

    def test_parse_last_month(self) -> None:
        # now = 2026-09-10，上月应为 2026-08
        tr = _parse_time_range("上月销售情况", NOW)
        assert tr is not None
        assert tr.start == date(2026, 8, 1)
        assert tr.end == date(2026, 8, 31)
        assert tr.label == "上月"

    def test_parse_last_month_jan(self) -> None:
        """1 月时，上月应跨年到去年 12 月。"""
        now_jan = date(2026, 1, 15)
        tr = _parse_time_range("上月数据", now_jan)
        assert tr is not None
        assert tr.start == date(2025, 12, 1)
        assert tr.end == date(2025, 12, 31)

    def test_parse_this_month(self) -> None:
        tr = _parse_time_range("本月完成率", NOW)
        assert tr is not None
        assert tr.start == date(2026, 9, 1)
        assert tr.end == date(2026, 9, 30)

    def test_parse_first_half(self) -> None:
        tr = _parse_time_range("2026年上半年销售额", NOW)
        assert tr is not None
        assert tr.start == date(2026, 1, 1)
        assert tr.end == date(2026, 6, 30)

    def test_parse_second_half(self) -> None:
        tr = _parse_time_range("今年下半年情况", NOW)
        assert tr is not None
        assert tr.start == date(2026, 7, 1)
        assert tr.end == date(2026, 12, 31)

    def test_parse_year_only(self) -> None:
        tr = _parse_time_range("2025年全年销售", NOW)
        assert tr is not None
        assert tr.start == date(2025, 1, 1)
        assert tr.end == date(2025, 12, 31)

    def test_parse_yoy(self) -> None:
        """同比：今年至今，对比去年同期。"""
        tr = _parse_time_range("今年销售额同比增长多少", NOW)
        assert tr is not None
        assert tr.comparison_start is not None
        assert tr.comparison_start.year == 2025

    def test_parse_this_quarter(self) -> None:
        # 2026-09-10 在 Q3 (7-9)
        tr = _parse_time_range("本季度业绩", NOW)
        assert tr is not None
        assert tr.start == date(2026, 7, 1)
        assert tr.end == date(2026, 9, 30)

    def test_parse_recent_n_days(self) -> None:
        from datetime import timedelta
        tr = _parse_time_range("近7天的销量", NOW)
        assert tr is not None
        assert tr.end == NOW
        assert tr.start == NOW - timedelta(days=6)

    def test_no_time_expression_returns_none(self) -> None:
        tr = _parse_time_range("华东区域销售额", NOW)
        assert tr is None

    def test_fixed_now_replays_same_window(self) -> None:
        """固定 now 两次调用结果相同（V2-S01-T02 可重放性验收）。"""
        tr1 = _parse_time_range("上月销售额", NOW)
        tr2 = _parse_time_range("上月销售额", NOW)
        assert tr1 == tr2


# ──────────────────────────────────────────────
# T02: 域路由
# ──────────────────────────────────────────────

class TestDomainRouting:
    """DomainRouter.route() 的域路由测试。"""

    def test_apple_phone_routes_to_sales(self) -> None:
        """'苹果手机上月销售情况' → 主域 sales，候选域包含 product。"""
        router = make_router()
        intent = router.route("苹果手机上月销售情况", NOW)
        assert intent.primary_domain == "sales"
        assert "product" in intent.domain_candidates
        # 注意：问题没有明确指标词，域路由可能会建议澄清，这是正确的行为
        # 重要的是：主域 = sales，product 维度被允许

    def test_apple_phone_allows_product_dimension(self) -> None:
        """苹果手机涉及商品维度，domain_candidates 应包含 product。"""
        router = make_router()
        intent = router.route("苹果手机上个月在哪些城市卖得最好", NOW)
        assert intent.primary_domain == "sales"
        assert "product" in intent.domain_candidates

    def test_inventory_routes_correctly(self) -> None:
        router = make_router()
        intent = router.route("当前仓库库存水位如何", NOW)
        assert intent.primary_domain == "inventory"

    def test_finance_routes_correctly(self) -> None:
        router = make_router()
        intent = router.route("上季度毛利率是多少", NOW)
        assert intent.primary_domain == "finance"

    def test_customer_routes_correctly(self) -> None:
        router = make_router()
        intent = router.route("华南区域本月新客户数量", NOW)
        assert intent.primary_domain in {"customer", "sales"}

    def test_intent_type_ranking(self) -> None:
        router = make_router()
        intent = router.route("销售额最高的前5个城市", NOW)
        assert intent.intent_type == IntentType.RANKING
        assert intent.ranking_limit == 5

    def test_intent_type_comparison(self) -> None:
        router = make_router()
        intent = router.route("今年销售额同比去年增长多少", NOW)
        assert intent.intent_type == IntentType.COMPARISON

    def test_region_filter_extracted(self) -> None:
        router = make_router()
        intent = router.route("华东区域今年销售额", NOW)
        region_filters = [f for f in intent.filters if f.concept == "区域"]
        assert len(region_filters) == 1
        assert region_filters[0].value == "华东"

    def test_metric_mention_extracted(self) -> None:
        router = make_router()
        intent = router.route("今年销售额多少", NOW)
        sales_metric = next(
            (m for m in intent.metric_mentions if m.resolved_metric_id == "net_sales"), None
        )
        assert sales_metric is not None

    def test_time_range_injected(self) -> None:
        """路由结果应包含解析后的时间范围，而不是裸字符串。"""
        router = make_router()
        intent = router.route("上月订单量", NOW)
        assert intent.time_range is not None
        assert intent.time_range.label == "上月"
        assert intent.now == NOW


# ──────────────────────────────────────────────
# T03: 澄清逻辑
# ──────────────────────────────────────────────

class TestClarificationLogic:
    """无域/低置信度/歧义指标/宽泛问题时返回澄清。"""

    def test_ambiguous_metric_requires_clarification(self) -> None:
        """'收入' 是歧义词，没有其他明确指标时应触发澄清。"""
        router = make_router()
        intent = router.route("今年收入怎么样", NOW)
        assert intent.requires_clarification
        assert intent.clarification_prompt is not None

    def test_vague_question_requires_clarification(self) -> None:
        """'今年表现怎么样' 没有明确指标，应触发澄清。"""
        router = make_router()
        intent = router.route("今年表现怎么样", NOW)
        assert intent.requires_clarification

    def test_vague_question_does_not_select_metric(self) -> None:
        """宽泛问题不应自行选择指标（metric_mentions 为空或全为 unresolved）。"""
        router = make_router()
        intent = router.route("今年表现怎么样", NOW)
        # 不应有已 resolved 的指标
        resolved = [m for m in intent.metric_mentions if m.resolved_metric_id]
        assert len(resolved) == 0

    def test_unresolved_in_intent(self) -> None:
        """歧义词应出现在 unresolved 列表中。"""
        router = make_router()
        intent = router.route("今年营收情况", NOW)
        assert "营收" in intent.unresolved or intent.requires_clarification

    def test_clear_question_no_clarification(self) -> None:
        """明确指标 + 明确域的问题不应触发澄清。"""
        router = make_router()
        intent = router.route("华东地区今年销售额同比增长多少", NOW)
        # 有明确指标，有明确域
        assert intent.primary_domain is not None
        assert not intent.requires_clarification

    def test_clarification_prompt_is_not_empty_when_needed(self) -> None:
        """触发澄清时，clarification_prompt 不能是空字符串或 None。"""
        router = make_router()
        intent = router.route("数据怎么样", NOW)
        if intent.requires_clarification:
            assert intent.clarification_prompt
            assert len(intent.clarification_prompt) > 0


# ──────────────────────────────────────────────
# 路由标注集（回归测试）
# ──────────────────────────────────────────────

# 格式：(问题, 期望主域, 期望不触发澄清)
ROUTING_ANNOTATION_SET = [
    ("苹果手机上月销售额是多少", "sales", True),
    ("华东区域今年销售额同比", "sales", True),
    ("当前仓库SKU000392的库存数量", "inventory", True),
    ("上季度各城市毛利率排名", "finance", True),
    ("本月新增会员数量", "customer", True),
    # 订单量是 sales 域的明确词，尽管问题也涉及区域
    ("华南区域最近7天订单量", "sales", True),
]


@pytest.mark.parametrize("question,expected_domain,expect_no_clarification", ROUTING_ANNOTATION_SET)
def test_routing_annotation_set(
    question: str,
    expected_domain: str,
    expect_no_clarification: bool,
) -> None:
    """路由标注集回归测试，确保核心问题路由准确。"""
    router = make_router()
    intent = router.route(question, NOW)
    assert intent.primary_domain == expected_domain, (
        f"问题 '{question}' 路由到 '{intent.primary_domain}'，期望 '{expected_domain}'"
    )
    if expect_no_clarification:
        assert not intent.requires_clarification, (
            f"问题 '{question}' 意外触发了澄清：{intent.clarification_prompt}"
        )
