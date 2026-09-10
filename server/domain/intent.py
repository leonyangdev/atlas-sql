"""QueryIntent：问数请求的结构化意图表示。

V2 的核心设计之一：先把自然语言转换为明确的意图结构，再进行域路由和 Schema 检索。
这样做的好处：
1. 意图解析与 SQL 生成解耦，可以独立测试和评测。
2. 时间表达式在此阶段统一解析，下游不再处理"今年""上个月"等歧义词。
3. 路由所需的置信度与 unresolved 片段透明可见，驱动澄清而非静默猜测。

调用关系：
  QueryOrchestrator → DomainRouter.route(question, now) → IntentParseResult
  IntentParseResult → SearchRepository.search_schema(intent)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date


class IntentType(enum.StrEnum):
    """问数请求的主意图类型。"""

    # 聚合统计类：求和、计数、平均
    ANALYTICAL = "analytical"
    # 排名类：前N、最高、最低
    RANKING = "ranking"
    # 比较类：同比、环比、两组对比
    COMPARISON = "comparison"
    # 明细查询类：列举记录
    DETAIL = "detail"
    # 趋势类：随时间变化
    TREND = "trend"
    # 不能识别的意图，需要澄清
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TimeRange:
    """解析后的时间范围，全部使用数据库时区（Asia/Shanghai）的日期边界。

    Examples:
        "今年" (now=2026-09-10) → TimeRange(start=2026-01-01, end=2026-12-31, label="今年")
        "上月" (now=2026-09-10) → TimeRange(start=2026-08-01, end=2026-08-31, label="上月")
        "2026年上半年"           → TimeRange(start=2026-01-01, end=2026-06-30, label="2026年上半年")
    """

    start: date
    end: date
    # 原始自然语言时间表达，用于 Prompt 和 Trace 展示
    label: str
    # 是否带有比较基准，例如"同比"对应上一年的同期
    comparison_start: date | None = None
    comparison_end: date | None = None


@dataclass(frozen=True)
class FilterCondition:
    """单个过滤条件：业务概念 + 原始值（此时尚未链接到具体字段）。

    Value Linking（V2-S04）会把 concept/value 映射到 column_id + typed_value。

    Examples:
        "华东区域" → FilterCondition(concept="区域", value="华东")
        "苹果手机" → FilterCondition(concept="品牌", value="苹果")
    """

    # 过滤的业务维度概念，例如"区域"、"品牌"、"品类"
    concept: str
    # 用户表达的原始值，例如"华东"、"苹果"
    value: str


@dataclass(frozen=True)
class MetricMention:
    """用户提及的指标或度量，尚未链接到正式指标 ID。

    Examples:
        "销售额" → MetricMention(text="销售额", resolved_metric_id="net_sales")
        "表现"   → MetricMention(text="表现", resolved_metric_id=None)  # 需要澄清
    """

    # 用户原始表达
    text: str
    # 已能映射到已知指标时填入，否则为 None
    resolved_metric_id: str | None = None


@dataclass(frozen=True)
class DimensionMention:
    """用户提及的维度，例如"城市"、"品类"、"渠道"。"""

    text: str
    # 已能映射到已知维度表时填入
    resolved_table: str | None = None


@dataclass
class QueryIntent:
    """一条问数请求的结构化意图。

    DomainRouter 解析后填写所有字段。下游模块只读此对象，不再解析原始自然语言。

    Attributes:
        intent_type: 主意图分类。
        metric_mentions: 用户提到的所有指标/度量，允许多个。
        dimension_mentions: 用户提到的所有维度，例如城市、品类。
        filters: 过滤条件列表，每项是一个业务概念 + 值。
        time_range: 解析后的时间范围；为 None 表示没有明确时间限定。
        ranking_limit: 排名类问题的 N 值，例如"前 5 名"→ 5。
        unresolved: 无法识别的片段，需要向用户澄清。
        domain_candidates: 候选业务域及置信度，例如 {"sales": 0.96, "finance": 0.51}。
        primary_domain: 置信度最高的业务域。
        requires_clarification: 是否需要在继续前向用户发问。
        clarification_prompt: 需要澄清时推荐的提示语。
        now: 路由时注入的当前时间，用于时间表达式的重放。
    """

    intent_type: IntentType
    metric_mentions: list[MetricMention] = field(default_factory=list)
    dimension_mentions: list[DimensionMention] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    time_range: TimeRange | None = None
    ranking_limit: int | None = None
    unresolved: list[str] = field(default_factory=list)
    domain_candidates: dict[str, float] = field(default_factory=dict)
    primary_domain: str | None = None
    requires_clarification: bool = False
    clarification_prompt: str | None = None
    # 路由时注入，确保重放时时间窗口一致
    now: date | None = None
