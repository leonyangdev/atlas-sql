"""域路由器：将自然语言问题解析为结构化 QueryIntent，并路由到业务域。

设计原则：
1. 注入 now（当前日期）而非直接调用 datetime.now()，保证测试可重放、线上可审计。
2. 时区固定为 Asia/Shanghai（UTC+8），所有时间表达解析都以此为基准。
3. 域路由基于规则+关键词得分，V2 够用；V3/V4 可替换为 LLM 分类或向量模型。
4. 找不到域、低置信度、歧义时间、未支持意图时返回 requires_clarification=True，
   绝不自行猜测，让编排器决定是否继续。

调用链：
    QueryOrchestrator.submit()
        → DomainRouter.route(question, now)
        → QueryIntent（包含 primary_domain、time_range、filters、unresolved）
        → SearchRepository.search_schema(intent)
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date

from server.domain.intent import (
    DimensionMention,
    FilterCondition,
    IntentType,
    MetricMention,
    QueryIntent,
    TimeRange,
)

# ──────────────────────────────────────────────
# 业务域知识库：关键词 → 域名 → 权重
# ──────────────────────────────────────────────

# 每个业务域的强触发词；出现一次则该域得分 +weight
_DOMAIN_KEYWORDS: dict[str, list[tuple[str, float]]] = {
    "sales": [
        ("销售", 1.0), ("订单", 1.0), ("销量", 0.9), ("销售额", 1.0),
        ("GMV", 0.9), ("净销售", 1.0), ("付款", 0.8), ("退款", 0.7),
        ("客单价", 0.8), ("有效订单", 0.9), ("苹果手机", 0.6),
        ("手机", 0.4), ("商品", 0.5), ("SKU", 0.8), ("品类", 0.5),
        ("订单量", 1.0), ("销售数量", 0.9),
    ],
    "product": [
        ("商品", 0.7), ("SKU", 0.9), ("品类", 0.8), ("品牌", 0.9),
        ("产品", 0.7), ("上架", 0.8), ("库存", 0.5), ("规格", 0.8),
    ],
    "customer": [
        ("客户", 1.0), ("会员", 0.9), ("用户", 0.8), ("新客", 0.9),
        ("老客", 0.9), ("复购", 0.9), ("活跃客户", 1.0), ("流失", 0.8),
    ],
    "store": [
        ("门店", 1.0), ("店铺", 0.9), ("城市", 0.7), ("区域", 0.4),
        ("华东", 0.5), ("华南", 0.5), ("华北", 0.5), ("华西", 0.5),
    ],
    "inventory": [
        ("库存", 1.0), ("仓库", 1.0), ("盘点", 1.0), ("补货", 0.9),
        ("调拨", 0.9), ("库存快照", 1.0), ("库存流水", 1.0),
    ],
    "finance": [
        ("财务", 1.0), ("成本", 0.9), ("毛利", 1.0), ("利润", 0.9),
        ("毛利率", 1.0), ("营收", 0.8), ("收入", 0.7), ("账期", 0.9),
    ],
    "marketing": [
        ("营销", 1.0), ("活动", 0.7), ("优惠券", 0.9), ("渠道", 0.9),
        ("投放", 1.0), ("触达", 1.0), ("ROI", 0.8), ("转化率", 0.7),
    ],
}

# sales 与 product 关联域：sales 查询通常需要商品维度
_RELATED_DOMAINS: dict[str, list[str]] = {
    "sales": ["product", "store"],
    "product": ["sales"],
    "customer": ["sales"],
    "store": ["sales"],
    "finance": ["sales"],
    "marketing": ["sales", "customer"],
    "inventory": ["product"],
}

# 置信度阈值
_HIGH_CONFIDENCE = 0.6   # 直接路由
_LOW_CONFIDENCE = 0.25   # 需要澄清

# ──────────────────────────────────────────────
# 意图类型关键词
# ──────────────────────────────────────────────

_RANKING_PATTERNS = re.compile(
    r"(前\s*(\d+)|排名|最高|最低|第一|末位|最多|最少|top\s*(\d+))", re.IGNORECASE
)
_COMPARISON_PATTERNS = re.compile(
    r"(同比|环比|对比|比较|相比|vs|versus|增长|下降|变化|增减)", re.IGNORECASE
)
_TREND_PATTERNS = re.compile(
    r"(趋势|走势|变化|每[月日周年季]|月度|季度|年度|逐[月日年])", re.IGNORECASE
)
_DETAIL_PATTERNS = re.compile(
    r"(列出|列举|哪些|明细|清单|show|list|detail)", re.IGNORECASE
)

# ──────────────────────────────────────────────
# 已知指标关键词（快速识别，不做精确链接）
# ──────────────────────────────────────────────

_KNOWN_METRICS: dict[str, str] = {
    "销售额": "net_sales",
    "净销售额": "net_sales",
    "销售收入": "net_sales",
    "GMV": "gmv",
    "订单量": "paid_order_count",
    "有效订单量": "paid_order_count",
    "销量": "sales_quantity",
    "销售数量": "sales_quantity",
    "客单价": "average_order_value",
    "退款金额": "refunded_amount",
    "退款率": "refund_rate",
    "毛利": "gross_margin",
    "毛利率": "gross_margin_rate",
    "复购率": "repeat_purchase_rate",
    "活跃客户": "active_customer_count",
    "新客户": "new_customer_count",
    "客户数": "customer_count",
}

# 歧义指标：单独出现无法确认是哪个域的指标
_AMBIGUOUS_METRIC_TEXTS = frozenset({"收入", "营收", "表现", "数据", "指标"})

# 已知维度关键词
_KNOWN_DIMENSIONS: dict[str, str] = {
    "城市": "dim_city",
    "区域": "dim_region",
    "门店": "dim_store",
    "品类": "dim_category",
    "品牌": "dim_brand",
    "商品": "dim_product",
    "渠道": "dim_sales_channel",
    "客户": "dim_customer",
}

# ──────────────────────────────────────────────
# 时间解析
# ──────────────────────────────────────────────

def _parse_time_range(question: str, now: date) -> TimeRange | None:
    """从问题中提取时间范围。

    支持表达式：今年、去年、今年上半年、今年下半年、本月、上月、本季度、上季度、
    近N天/月、YYYY年、YYYY年Q季度、YYYY年上/下半年。

    时区：Asia/Shanghai（UTC+8），所有日期边界使用上海时区的零点。
    返回 None 表示问题中没有时间相关词，由下游决定是否需要澄清。
    """
    y, m = now.year, now.month

    # 上半年 / 下半年（先于"今年"检测，避免"今年下半年"被今年规则截断）
    if re.search(r"上半年", question):
        year = _extract_year(question, y)
        start = date(year, 1, 1)
        end = date(year, 6, 30)
        return TimeRange(start=start, end=end, label=f"{year}年上半年")
    if re.search(r"下半年", question):
        year = _extract_year(question, y)
        start = date(year, 7, 1)
        end = date(year, 12, 31)
        return TimeRange(start=start, end=end, label=f"{year}年下半年")

    # 今年
    if re.search(r"今年", question):
        start = date(y, 1, 1)
        end = date(y, 12, 31)
        label = "今年"
        # 同比则比较去年
        comparison = _yoy_range(start, end) if re.search(r"同比", question) else None
        return TimeRange(
            start=start, end=end, label=label,
            comparison_start=comparison[0] if comparison else None,
            comparison_end=comparison[1] if comparison else None,
        )

    # 去年
    if re.search(r"去年|上一年|上年", question):
        start = date(y - 1, 1, 1)
        end = date(y - 1, 12, 31)
        return TimeRange(start=start, end=end, label="去年")

    # 本月
    if re.search(r"本月|这个月", question):
        start = date(y, m, 1)
        end = date(y, m, monthrange(y, m)[1])
        label = "本月"
        comparison = _mom_range(start, end) if re.search(r"环比", question) else None
        return TimeRange(
            start=start, end=end, label=label,
            comparison_start=comparison[0] if comparison else None,
            comparison_end=comparison[1] if comparison else None,
        )

    # 上月 / 上个月
    if re.search(r"上月|上个月|上一月", question):
        # 向前推一个月
        if m == 1:
            prev_y, prev_m = y - 1, 12
        else:
            prev_y, prev_m = y, m - 1
        start = date(prev_y, prev_m, 1)
        end = date(prev_y, prev_m, monthrange(prev_y, prev_m)[1])
        return TimeRange(start=start, end=end, label="上月")

    # 本季度
    if re.search(r"本季度|这季度", question):
        q = (m - 1) // 3 + 1
        start = date(y, (q - 1) * 3 + 1, 1)
        end_m = q * 3
        end = date(y, end_m, monthrange(y, end_m)[1])
        return TimeRange(start=start, end=end, label="本季度")

    # 上季度
    if re.search(r"上季度|上一季度", question):
        q = (m - 1) // 3 + 1
        prev_q = q - 1 if q > 1 else 4
        prev_q_y = y if q > 1 else y - 1
        start = date(prev_q_y, (prev_q - 1) * 3 + 1, 1)
        end_m = prev_q * 3
        end = date(prev_q_y, end_m, monthrange(prev_q_y, end_m)[1])
        return TimeRange(start=start, end=end, label="上季度")

    # 近N天
    m_near_days = re.search(r"近\s*(\d+)\s*天", question)
    if m_near_days:
        n = int(m_near_days.group(1))
        from datetime import timedelta
        end = now
        start = now - timedelta(days=n - 1)
        return TimeRange(start=start, end=end, label=f"近{n}天")

    # YYYY年（精确年份）
    m_year = re.search(r"(\d{4})\s*年(?!\s*[上下]半年)", question)
    if m_year:
        year = int(m_year.group(1))
        if 2000 <= year <= now.year + 1:
            start = date(year, 1, 1)
            end = date(year, 12, 31)
            return TimeRange(start=start, end=end, label=f"{year}年")

    # 同比但没有指定时间（取今年，比较去年同期）
    if re.search(r"同比", question):
        start = date(y, 1, 1)
        end = now
        comparison = _yoy_range(start, end)
        return TimeRange(
            start=start, end=end, label="今年至今",
            comparison_start=comparison[0],
            comparison_end=comparison[1],
        )

    return None


def _extract_year(question: str, default: int) -> int:
    """从问题中提取 YYYY 年份，找不到则返回 default。"""
    m = re.search(r"(\d{4})\s*年", question)
    if m:
        year = int(m.group(1))
        if 2000 <= year <= 2100:
            return year
    return default


def _yoy_range(start: date, end: date) -> tuple[date, date]:
    """计算同比（上一年同期）范围。"""
    return date(start.year - 1, start.month, start.day), date(end.year - 1, end.month, end.day)


def _mom_range(start: date, end: date) -> tuple[date, date]:
    """计算环比（上一个月同期）范围。"""
    y, m = start.year, start.month
    if m == 1:
        py, pm = y - 1, 12
    else:
        py, pm = y, m - 1
    prev_start = date(py, pm, 1)
    prev_end = date(py, pm, monthrange(py, pm)[1])
    return prev_start, prev_end


# ──────────────────────────────────────────────
# 过滤条件提取（简单规则，V3 可升级为 NER）
# ──────────────────────────────────────────────

# 区域关键词：出现则添加 region 过滤
_REGION_FILTERS: dict[str, str] = {
    "华东": "华东", "华南": "华南", "华北": "华北",
    "华西": "华西", "华中": "华中", "东北": "东北",
    "西南": "西南", "西北": "西北",
}


def _extract_filters(question: str) -> list[FilterCondition]:
    """从问题中提取明确的过滤条件。

    当前只提取区域关键词；V3 Value Linking 阶段会进一步扩展。
    """
    filters: list[FilterCondition] = []
    for keyword, value in _REGION_FILTERS.items():
        if keyword in question:
            filters.append(FilterCondition(concept="区域", value=value))
    return filters


# ──────────────────────────────────────────────
# 公开接口
# ──────────────────────────────────────────────

class DomainRouter:
    """将自然语言问题路由到业务域并提取结构化意图。

    无状态类，所有外部状态（now、domain_keywords）通过构造或参数传入，
    方便测试和不同环境配置。
    """

    def __init__(
        self,
        domain_keywords: dict[str, list[tuple[str, float]]] | None = None,
        high_confidence: float = _HIGH_CONFIDENCE,
        low_confidence: float = _LOW_CONFIDENCE,
    ) -> None:
        """
        Args:
            domain_keywords: 自定义域关键词权重表，None 时使用内置表。
            high_confidence: 直接路由阈值，超过则无需澄清。
            low_confidence: 低于此阈值则要求澄清。
        """
        self._domain_keywords = domain_keywords or _DOMAIN_KEYWORDS
        self._high_confidence = high_confidence
        self._low_confidence = low_confidence

    def route(self, question: str, now: date) -> QueryIntent:
        """解析问题，返回带域路由的结构化意图。

        Args:
            question: 用户自然语言问题（已去除首尾空白）。
            now: 当前日期，用于时间表达式解析；必须由调用方注入，不允许内部调用 date.today()。

        Returns:
            QueryIntent，包含 primary_domain、time_range、filters、unresolved 等字段。
        """
        # 1. 计算各域得分
        domain_scores = self._score_domains(question)

        # 2. 确定主域和候选域
        primary_domain, candidates = self._select_primary(domain_scores)

        # 3. 解析意图类型
        intent_type = self._detect_intent_type(question)

        # 4. 提取指标和维度提及
        metric_mentions = self._extract_metrics(question)
        dimension_mentions = self._extract_dimensions(question)

        # 5. 解析时间范围
        time_range = _parse_time_range(question, now)

        # 6. 提取过滤条件
        filters = _extract_filters(question)

        # 7. 提取排名 N 值
        ranking_limit = self._extract_ranking_limit(question)

        # 8. 收集 unresolved 片段（无法识别的指标表达）
        unresolved = self._find_unresolved(question, metric_mentions)

        # 9. 判断是否需要澄清
        requires_clarification, clarification_prompt = self._check_clarification(
            primary_domain=primary_domain,
            candidates=candidates,
            metric_mentions=metric_mentions,
            unresolved=unresolved,
            time_range=time_range,
            question=question,
        )

        return QueryIntent(
            intent_type=intent_type,
            metric_mentions=metric_mentions,
            dimension_mentions=dimension_mentions,
            filters=filters,
            time_range=time_range,
            ranking_limit=ranking_limit,
            unresolved=unresolved,
            domain_candidates=candidates,
            primary_domain=primary_domain,
            requires_clarification=requires_clarification,
            clarification_prompt=clarification_prompt,
            now=now,
        )

    # ── 内部方法 ──────────────────────────────

    def _score_domains(self, question: str) -> dict[str, float]:
        """计算每个业务域的关键词命中得分。"""
        scores: dict[str, float] = {}
        for domain, keywords in self._domain_keywords.items():
            score = 0.0
            for keyword, weight in keywords:
                if keyword in question:
                    score += weight
            if score > 0:
                scores[domain] = score
        return scores

    def _select_primary(
        self, scores: dict[str, float]
    ) -> tuple[str | None, dict[str, float]]:
        """选择得分最高的主域，并加入必要关联域。

        关联域的置信度设为主域的 60%，但最高不超过 0.5，表示"可能需要关联"。
        """
        if not scores:
            return None, {}

        # 归一化到 [0, 1]
        max_score = max(scores.values())
        normalized: dict[str, float] = {
            d: min(1.0, s / max(max_score, 1.0))
            for d, s in scores.items()
        }

        # 主域 = 得分最高的域
        primary = max(normalized, key=lambda d: normalized[d])

        # 关联域
        for related in _RELATED_DOMAINS.get(primary, []):
            if related not in normalized:
                normalized[related] = min(0.5, normalized[primary] * 0.6)

        # 按得分降序排列
        candidates = dict(
            sorted(normalized.items(), key=lambda x: x[1], reverse=True)
        )
        return primary, candidates

    def _detect_intent_type(self, question: str) -> IntentType:
        """根据关键词模式判断主意图类型。

        优先级：比较 > 排名 > 趋势 > 明细 > 分析（默认）。
        """
        if _COMPARISON_PATTERNS.search(question):
            return IntentType.COMPARISON
        if _RANKING_PATTERNS.search(question):
            return IntentType.RANKING
        if _TREND_PATTERNS.search(question):
            return IntentType.TREND
        if _DETAIL_PATTERNS.search(question):
            return IntentType.DETAIL
        return IntentType.ANALYTICAL

    def _extract_metrics(self, question: str) -> list[MetricMention]:
        """识别已知指标词，返回带 resolved_metric_id 的列表。"""
        mentions: list[MetricMention] = []
        seen: set[str] = set()
        # 按词长降序匹配，防止"净销售额"被"销售额"先截断
        for text in sorted(_KNOWN_METRICS, key=len, reverse=True):
            if text in question and text not in seen:
                mentions.append(
                    MetricMention(text=text, resolved_metric_id=_KNOWN_METRICS[text])
                )
                seen.add(text)
        # 歧义指标（如"收入"）也收集，标记 unresolved
        for text in _AMBIGUOUS_METRIC_TEXTS:
            if text in question and text not in seen:
                mentions.append(MetricMention(text=text, resolved_metric_id=None))
                seen.add(text)
        return mentions

    def _extract_dimensions(self, question: str) -> list[DimensionMention]:
        """识别已知维度词。"""
        mentions: list[DimensionMention] = []
        seen: set[str] = set()
        for text, table in sorted(_KNOWN_DIMENSIONS.items(), key=lambda x: len(x[0]), reverse=True):
            if text in question and text not in seen:
                mentions.append(DimensionMention(text=text, resolved_table=table))
                seen.add(text)
        return mentions

    def _extract_ranking_limit(self, question: str) -> int | None:
        """提取排名类问题的 N 值，例如"前5名"→ 5。"""
        m = re.search(r"前\s*(\d+)", question)
        if m:
            return int(m.group(1))
        m = re.search(r"top\s*(\d+)", question, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None

    def _find_unresolved(
        self, question: str, metric_mentions: list[MetricMention]
    ) -> list[str]:
        """返回歧义指标文本（resolved_metric_id 为 None 的那些）。"""
        return [m.text for m in metric_mentions if m.resolved_metric_id is None]

    def _check_clarification(
        self,
        *,
        primary_domain: str | None,
        candidates: dict[str, float],
        metric_mentions: list[MetricMention],
        unresolved: list[str],
        time_range: "TimeRange | None",  # noqa: F821
        question: str,
    ) -> tuple[bool, str | None]:
        """判断是否需要向用户澄清，并生成提示语。

        触发澄清的条件：
        1. 找不到任何域（candidates 为空）
        2. 主域置信度低于阈值
        3. 存在歧义指标（如"收入""表现"）且没有其他明确指标
        4. 没有找到任何指标且问题非常模糊（例如"今年表现怎么样"）
        """
        # 条件 1：找不到任何域
        if not candidates or primary_domain is None:
            return True, "请问您想查询哪个业务领域的数据？例如：销售、客户、库存或财务？"

        # 条件 2：主域置信度过低
        primary_score = candidates.get(primary_domain, 0.0)
        if primary_score < self._low_confidence:
            return True, f"您的问题涉及多个业务领域，请问主要想查询 {primary_domain} 还是其他领域？"

        # 条件 3：全部指标都是歧义词，没有明确指标
        has_resolved = any(m.resolved_metric_id is not None for m in metric_mentions)
        if unresolved and not has_resolved:
            names = "、".join(unresolved)
            return True, f'"{names}"可能对应多种指标，您希望查询哪个？例如：销售额、毛利率、客户数？'

        # 条件 4：没有任何指标提及，问题过于宽泛
        if not metric_mentions and not unresolved:
            # 有时间词或维度词的宽泛问题，例如"今年表现怎么样"
            vague_words = ["表现", "情况", "怎么样", "如何", "怎样", "数据"]
            if any(w in question for w in vague_words):
                return True, "您想查看哪方面的数据？例如：销售额、订单量、毛利率还是客户增长？"

        return False, None
