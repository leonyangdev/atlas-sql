"""Schema Linking：将问题片段映射到具体的表列或指标占位。

Schema Retrieval（检索层）解决"哪些 Schema 可能相关"；
Schema Linking（链接层）进一步解决"用户问的每个业务概念到底对应哪个字段"。

这两个阶段的输出形式不同：
- Retrieval 输出：Candidate 列表（相关性排序）
- Linking 输出：SchemaLink 列表（概念 → 物理对象 的确定映射）

设计原则：
1. 每个 SchemaLink 都保存 evidence（证据来源）和 confidence（置信度），
   供调试、消融分析和失败归因使用。
2. 同一概念有多个候选时，记为 conflict，触发澄清，不静默选择。
3. 严格区分 retrieval 输出（候选）和 linking 输出（确定映射），
   不把"召回到了"等同于"已链接"。
4. 指标（metric）和物理列（column）用不同的 link_type 区分，
   因为指标是计算表达式，生成 SQL 时需要展开，而不是直接引用字段名。

调用链：
    SchemaLinker.link(question, intent, schema_context)
        → 对每个 metric_mention 查找对应指标
        → 对每个 dimension_mention / filter 查找对应列
        → 返回 SchemLinkResult
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any

from server.domain.intent import FilterCondition, MetricMention, QueryIntent
from server.search.retrieval import SchemaContext

logger = logging.getLogger(__name__)


class LinkType(enum.StrEnum):
    """链接的目标类型。"""

    COLUMN = "column"      # 指向物理列（table.column）
    METRIC = "metric"      # 指向语义层指标（需要 V3 展开）
    TABLE = "table"        # 指向整张表（例如维度表）
    UNKNOWN = "unknown"    # 无法确定


@dataclass(frozen=True)
class SchemaLink:
    """一个概念片段的链接结果。

    Attributes:
        source_text: 用户原始表达，例如"销售额"、"华东"。
        link_type: 链接的目标类型。
        target_id: 目标的稳定 ID，列格式为 "column:{ds}:{schema}:{table}:{column}"，
                   指标格式为 "metric:{metric_id}"。
        target_label: 目标的展示名称，例如 "fact_order_item.net_amount"。
        confidence: 0-1 之间的置信度。
        evidence: 链接依据，例如 "exact_metric_alias"、"bm25_top1"、"manual_alias"。
        conflict_candidates: 如果有多个候选，列出所有候选 target_id。
        requires_clarification: 有冲突或置信度低时为 True。
    """

    source_text: str
    link_type: LinkType
    target_id: str
    target_label: str
    confidence: float
    evidence: str
    conflict_candidates: list[str] = field(default_factory=list)
    requires_clarification: bool = False


@dataclass
class SchemaLinkResult:
    """整条问题的 Schema Linking 结果。

    Attributes:
        links: 所有已链接的概念映射（包括指标和维度）。
        unlinked_texts: 无法映射到任何 Schema 对象的概念片段。
        requires_clarification: 是否存在冲突或无法确定的链接，需要向用户澄清。
        clarification_prompt: 澄清提示语。
    """

    links: list[SchemaLink] = field(default_factory=list)
    unlinked_texts: list[str] = field(default_factory=list)
    requires_clarification: bool = False
    clarification_prompt: str | None = None

    def get_linked_metric_ids(self) -> list[str]:
        """返回已链接的指标 ID 列表，供 SQL 生成阶段使用。"""
        return [
            lnk.target_id.removeprefix("metric:")
            for lnk in self.links
            if lnk.link_type == LinkType.METRIC
        ]

    def get_linked_columns(self) -> list[tuple[str, str]]:
        """返回已链接的列，格式为 (table_name, column_name) 列表。"""
        result = []
        for lnk in self.links:
            if lnk.link_type == LinkType.COLUMN and lnk.target_label:
                parts = lnk.target_label.split(".")
                if len(parts) == 2:
                    result.append((parts[0], parts[1]))
        return result


class SchemaLinker:
    """将问题中的业务概念链接到 SchemaContext 中的物理对象。

    Args:
        metric_id_map: 指标别名 → 指标 ID 的映射，例如 {"销售额": "net_sales"}。
                       V3 阶段从 SemanticLayer 加载；V2 使用草稿版本。
        confidence_threshold: 低于此值视为不确定，加入 unlinked_texts。
    """

    def __init__(
        self,
        metric_id_map: dict[str, str] | None = None,
        confidence_threshold: float = 0.6,
    ) -> None:
        self._metric_map = metric_id_map or _DEFAULT_METRIC_MAP
        self._threshold = confidence_threshold

    def link(
        self,
        question: str,
        intent: QueryIntent,
        schema_context: SchemaContext,
    ) -> SchemaLinkResult:
        """对一条问题执行 Schema Linking，返回链接结果。

        Args:
            question: 用户原始问题。
            intent: 域路由 + 意图解析结果（含 metric_mentions、filters 等）。
            schema_context: 两级召回结果（候选表和列）。
        """
        links: list[SchemaLink] = []
        unlinked: list[str] = []

        # 1. 链接指标提及
        for mention in intent.metric_mentions:
            link = self._link_metric(mention)
            if link:
                links.append(link)
            else:
                unlinked.append(mention.text)

        # 2. 链接维度提及（定位到具体维度表）
        for dim in intent.dimension_mentions:
            link = self._link_dimension(dim.text, schema_context)
            if link:
                links.append(link)

        # 3. 链接过滤条件中的概念（定位到列）
        for flt in intent.filters:
            link = self._link_filter_concept(flt, schema_context)
            if link:
                links.append(link)

        # 4. 检查是否有冲突或低置信度需要澄清
        conflicted = [lnk for lnk in links if lnk.requires_clarification]
        requires_clarification = bool(unlinked or conflicted)
        clarification = None
        if requires_clarification:
            parts = []
            if unlinked:
                parts.append(f"无法识别的概念：{"、".join(unlinked)}")
            if conflicted:
                parts.append(f"存在歧义的概念：{"、".join(lnk.source_text for lnk in conflicted)}")
            clarification = "；".join(parts) + "，请您进一步说明。"

        return SchemaLinkResult(
            links=links,
            unlinked_texts=unlinked,
            requires_clarification=requires_clarification,
            clarification_prompt=clarification,
        )

    # ── 内部方法 ────────────────────────────────────────

    def _link_metric(self, mention: MetricMention) -> SchemaLink | None:
        """将指标提及链接到正式指标 ID。

        优先级：
        1. resolved_metric_id 已经在域路由阶段填写（来自 METRIC_ALIASES）
        2. 在 _DEFAULT_METRIC_MAP 中精确匹配
        """
        if mention.resolved_metric_id:
            return SchemaLink(
                source_text=mention.text,
                link_type=LinkType.METRIC,
                target_id=f"metric:{mention.resolved_metric_id}",
                target_label=mention.resolved_metric_id,
                confidence=0.95,
                evidence="resolved_by_domain_router",
            )

        # 精确匹配
        metric_id = self._metric_map.get(mention.text)
        if metric_id:
            return SchemaLink(
                source_text=mention.text,
                link_type=LinkType.METRIC,
                target_id=f"metric:{metric_id}",
                target_label=metric_id,
                confidence=0.9,
                evidence="exact_alias_match",
            )

        # 找不到 → 返回 None，调用方记入 unlinked
        return None

    def _link_dimension(
        self, text: str, schema_context: SchemaContext
    ) -> SchemaLink | None:
        """将维度关键词链接到候选表中的具体表。"""
        # 在召回的表中查找 business_name 或 table_name 包含该维度词的表
        matches: list[str] = []
        for table in schema_context.tables:
            business_name = table.payload.get("business_name", "")
            table_name = table.payload.get("table_name", "")
            if text in business_name or text in table_name:
                matches.append(table.payload.get("table_name", table.doc_id))

        if len(matches) == 1:
            return SchemaLink(
                source_text=text,
                link_type=LinkType.TABLE,
                target_id=f"table:{matches[0]}",
                target_label=matches[0],
                confidence=0.85,
                evidence="table_name_match",
            )

        if len(matches) > 1:
            # 多个候选 → 冲突，需要澄清
            return SchemaLink(
                source_text=text,
                link_type=LinkType.TABLE,
                target_id=f"table:{matches[0]}",
                target_label=matches[0],
                confidence=0.5,
                evidence="multiple_table_matches",
                conflict_candidates=[f"table:{t}" for t in matches],
                requires_clarification=True,
            )

        return None

    def _link_filter_concept(
        self, flt: FilterCondition, schema_context: SchemaContext
    ) -> SchemaLink | None:
        """将过滤条件的 concept 链接到候选列。

        例如："区域"过滤 → dim_region.region_name 列。
        """
        # 在候选列中找 business_name 或 column_name 与 concept 匹配的列
        matches: list[Any] = []
        for col in schema_context.columns:
            business_name = col.payload.get("business_name", "")
            col_name = col.payload.get("column_name", "")
            table_name = col.payload.get("table_name", "")
            if flt.concept in business_name or flt.concept in col_name:
                matches.append((table_name, col_name, col.doc_id))

        if len(matches) == 1:
            table_name, col_name, doc_id = matches[0]
            return SchemaLink(
                source_text=flt.concept,
                link_type=LinkType.COLUMN,
                target_id=doc_id,
                target_label=f"{table_name}.{col_name}",
                confidence=0.85,
                evidence="column_name_match",
            )

        if len(matches) > 1:
            table_name, col_name, doc_id = matches[0]
            return SchemaLink(
                source_text=flt.concept,
                link_type=LinkType.COLUMN,
                target_id=doc_id,
                target_label=f"{table_name}.{col_name}",
                confidence=0.5,
                evidence="multiple_column_matches",
                conflict_candidates=[m[2] for m in matches],
                requires_clarification=True,
            )

        return None


# ── 默认指标别名映射（V2 草稿，V3 从 SemanticLayer 替换）──────────────────
_DEFAULT_METRIC_MAP: dict[str, str] = {
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
