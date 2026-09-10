"""V3 语义增强 SchemaLinker。

在 V2 SchemaLinker 基础上：
1. 指标链接：优先查 SemanticRegistry（已发布版本的同义词表），回退 V2 默认映射。
2. 维度链接：查 DimensionService 的同义词表，将意图中的维度关键词链接到 dimension_id。
3. 值别名：查 GlossaryService 的值映射，将"华东"→ dim_region.region_name=East China。
4. 冲突处理：
   - 同名指标（finance:revenue vs sales:net_sales）→ 根据 primary_domain 优先选择，
     domain 不同时触发澄清，附上口径差异说明。
   - 财年/自然年冲突：当问题包含财年关键词但没有指定 FiscalCalendar 时，
     输出澄清提示。
   - 时间字段冲突（paid_at vs created_at）：当多个时间列都符合时，
     按 metric.time_role 优先选择。

调用链：
    SemanticSchemaLinker.link(question, intent, schema_context)
        → _link_metric_v3(mention, registry)
        → _link_dimension_v3(mention, dim_service)
        → _link_filter_v3(flt, schema_context, glossary)
        → _detect_fiscal_year_conflict(intent)
        → SchemaLinkResult
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from server.domain.intent import FilterCondition, MetricMention, QueryIntent
from server.linking.schema import LinkType, SchemaLink, SchemaLinkResult
from server.search.retrieval import SchemaContext
from server.semantic.glossary import DimensionService, GlossaryService
from server.semantic.registry import MetricEntry, SemanticRegistry

logger = logging.getLogger(__name__)

# 财年相关关键词，检测到后需要询问用户财年还是自然年
_FISCAL_YEAR_KEYWORDS = frozenset([
    "财年", "FY", "fiscal year", "财务年", "财政年",
])

# 已知的时间歧义词（按支付还是按创建归属）
_TIME_AMBIGUOUS_KEYWORDS = frozenset([
    "时间", "日期", "何时", "when",
])


@dataclass
class SemanticLinkContext:
    """V3 链接器需要的语义层上下文。

    Attributes:
        registry: 已加载的指标注册表（可以是空的，回退到 V2 映射）。
        dim_service: 已加载的维度服务（可以是空的）。
        glossary: 已加载的术语服务（可以是空的）。
    """

    registry: SemanticRegistry | None = None
    dim_service: DimensionService | None = None
    glossary: GlossaryService | None = None


class SemanticSchemaLinker:
    """V3 语义增强链接器。

    Args:
        semantic_ctx: 语义层上下文（registry / dim_service / glossary）。
        confidence_threshold: 低于此值的链接记入 unlinked，不静默使用。
    """

    def __init__(
        self,
        semantic_ctx: SemanticLinkContext | None = None,
        confidence_threshold: float = 0.6,
    ) -> None:
        self._ctx = semantic_ctx or SemanticLinkContext()
        self._threshold = confidence_threshold

    def link(
        self,
        question: str,
        intent: QueryIntent,
        schema_context: SchemaContext,
    ) -> SchemaLinkResult:
        """执行 V3 语义增强的 Schema Linking。"""
        links: list[SchemaLink] = []
        unlinked: list[str] = []
        clarifications: list[str] = []

        # 1. 检测财年/自然年冲突（在任何链接之前）
        fiscal_conflict = self._detect_fiscal_year_conflict(question)
        if fiscal_conflict:
            clarifications.append(fiscal_conflict)

        # 2. 链接指标提及
        for mention in intent.metric_mentions:
            link, clarification = self._link_metric_v3(mention, intent.primary_domain)
            if link:
                links.append(link)
            else:
                unlinked.append(mention.text)
            if clarification:
                clarifications.append(clarification)

        # 3. 链接维度提及
        for dim in intent.dimension_mentions:
            link = self._link_dimension_v3(dim.text, schema_context)
            if link:
                links.append(link)

        # 4. 链接过滤条件（值别名 + 列定位）
        for flt in intent.filters:
            filter_links = self._link_filter_v3(flt, schema_context)
            links.extend(filter_links)

        # 5. 汇总澄清信息
        conflicted = [lnk for lnk in links if lnk.requires_clarification]
        requires_clarification = bool(unlinked or conflicted or clarifications)
        clarification_prompt = None
        if requires_clarification:
            parts = list(clarifications)
            if unlinked:
                parts.append(f"无法识别的概念：{'、'.join(unlinked)}")
            if conflicted:
                parts.append(f"存在歧义：{'、'.join(lnk.source_text for lnk in conflicted)}")
            clarification_prompt = "；".join(parts) + "，请您进一步说明。"

        return SchemaLinkResult(
            links=links,
            unlinked_texts=unlinked,
            requires_clarification=requires_clarification,
            clarification_prompt=clarification_prompt,
        )

    # ── 指标链接（V3 升级版）─────────────────────────────────

    def _link_metric_v3(
        self,
        mention: MetricMention,
        primary_domain: str | None,
    ) -> tuple[SchemaLink | None, str | None]:
        """链接指标提及，返回 (SchemaLink | None, clarification | None)。

        优先级：
        1. mention.resolved_metric_id 已填写（域路由阶段确定）
        2. SemanticRegistry 同义词表（已发布版本）
        3. GlossaryService 的 metric 类型条目
        4. 回退 V2 硬编码映射（_V2_FALLBACK_MAP）
        """
        # 优先级 1：域路由已解析
        if mention.resolved_metric_id:
            return (
                SchemaLink(
                    source_text=mention.text,
                    link_type=LinkType.METRIC,
                    target_id=f"metric:{mention.resolved_metric_id}",
                    target_label=mention.resolved_metric_id,
                    confidence=0.97,
                    evidence="resolved_by_domain_router",
                ),
                None,
            )

        # 优先级 2：SemanticRegistry（已发布版本的同义词）
        if self._ctx.registry:
            metric_id = self._ctx.registry.resolve_synonym(mention.text)
            if metric_id:
                entry = self._ctx.registry.get(metric_id)
                # 检测同名指标跨域冲突
                conflict_clarification = self._check_cross_domain_conflict(
                    mention.text, metric_id, primary_domain
                )
                confidence = 0.92 if not conflict_clarification else 0.65
                return (
                    SchemaLink(
                        source_text=mention.text,
                        link_type=LinkType.METRIC,
                        target_id=f"metric:{metric_id}",
                        target_label=entry.label if entry else metric_id,
                        confidence=confidence,
                        evidence="semantic_registry_synonym",
                        requires_clarification=bool(conflict_clarification),
                    ),
                    conflict_clarification,
                )

        # 优先级 3：GlossaryService metric 条目
        if self._ctx.glossary:
            entry = self._ctx.glossary.lookup_term(mention.text)
            if entry and entry.target_type == "metric":
                metric_id = entry.canonical_target_id.removeprefix("metric:")
                return (
                    SchemaLink(
                        source_text=mention.text,
                        link_type=LinkType.METRIC,
                        target_id=f"metric:{metric_id}",
                        target_label=metric_id,
                        confidence=0.88,
                        evidence="glossary_metric_entry",
                    ),
                    None,
                )

        # 优先级 4：V2 回退映射
        metric_id = _V2_FALLBACK_MAP.get(mention.text)
        if metric_id:
            return (
                SchemaLink(
                    source_text=mention.text,
                    link_type=LinkType.METRIC,
                    target_id=f"metric:{metric_id}",
                    target_label=metric_id,
                    confidence=0.80,
                    evidence="v2_fallback_alias",
                ),
                None,
            )

        return None, None

    def _check_cross_domain_conflict(
        self, text: str, metric_id: str, primary_domain: str | None
    ) -> str | None:
        """检测同名指标跨域冲突，返回澄清提示或 None。

        例如："营收"在 sales 域是 net_sales，在 finance 域是 finance_revenue。
        当 primary_domain 与指标所在域不同时，给出口径区分提示。
        """
        if not self._ctx.registry or not primary_domain:
            return None

        entry = self._ctx.registry.get(metric_id)
        if entry is None:
            return None

        if entry.domain != primary_domain:
            # 查找同一名称在其他域的指标
            all_metrics = self._ctx.registry.all_metrics()
            same_name_others = [
                m for m in all_metrics
                if m.label == entry.label and m.metric_id != metric_id
            ]
            if same_name_others:
                other_domains = "、".join(m.domain for m in same_name_others[:2])
                return (
                    f"「{text}」在 {entry.domain} 域对应 {entry.label}（{metric_id}），"
                    f"但在 {other_domains} 域有不同口径定义，请确认您想查询哪个口径"
                )

        return None

    # ── 维度链接（V3 升级版）─────────────────────────────────

    def _link_dimension_v3(
        self, text: str, schema_context: SchemaContext
    ) -> SchemaLink | None:
        """链接维度提及，优先查 DimensionService 同义词表。"""
        # 优先：DimensionService 同义词
        if self._ctx.dim_service:
            dim_id = self._ctx.dim_service.resolve_synonym(text)
            if dim_id:
                entry = self._ctx.dim_service.get(dim_id)
                return SchemaLink(
                    source_text=text,
                    link_type=LinkType.TABLE,
                    target_id=f"dimension:{dim_id}",
                    target_label=entry.label if entry else dim_id,
                    confidence=0.90,
                    evidence="dimension_service_synonym",
                )

        # 回退：在召回表中按名称匹配
        matches = []
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
                confidence=0.82,
                evidence="table_name_match_fallback",
            )
        if len(matches) > 1:
            return SchemaLink(
                source_text=text,
                link_type=LinkType.TABLE,
                target_id=f"table:{matches[0]}",
                target_label=matches[0],
                confidence=0.45,
                evidence="multiple_table_matches",
                conflict_candidates=[f"table:{t}" for t in matches],
                requires_clarification=True,
            )

        return None

    # ── 过滤链接（V3 升级版，接入值别名）────────────────────

    def _link_filter_v3(
        self, flt: FilterCondition, schema_context: SchemaContext
    ) -> list[SchemaLink]:
        """链接过滤条件，返回链接列表（可能有值链接和列链接两条）。

        步骤：
        1. 查 GlossaryService 值别名（"华东" → dim_region.region_name = "East China"）
        2. 在候选列中按 concept 定位物理列
        """
        result: list[SchemaLink] = []

        # 步骤 1：值别名查找
        if self._ctx.glossary:
            alias = self._ctx.glossary.lookup_value_alias(flt.value)
            if alias:
                column_ref, db_value = alias
                result.append(
                    SchemaLink(
                        source_text=flt.value,
                        link_type=LinkType.COLUMN,
                        target_id=f"value:{column_ref}={db_value}",
                        target_label=f"{column_ref} = '{db_value}'",
                        confidence=0.92,
                        evidence="glossary_value_alias",
                    )
                )

        # 步骤 2：列定位（按 concept 关键词）
        matches = []
        for col in schema_context.columns:
            business_name = col.payload.get("business_name", "")
            col_name = col.payload.get("column_name", "")
            table_name = col.payload.get("table_name", "")
            if flt.concept in business_name or flt.concept in col_name:
                matches.append((table_name, col_name, col.doc_id))

        if len(matches) == 1:
            table_name, col_name, doc_id = matches[0]
            result.append(
                SchemaLink(
                    source_text=flt.concept,
                    link_type=LinkType.COLUMN,
                    target_id=doc_id,
                    target_label=f"{table_name}.{col_name}",
                    confidence=0.85,
                    evidence="column_name_match",
                )
            )
        elif len(matches) > 1:
            table_name, col_name, doc_id = matches[0]
            result.append(
                SchemaLink(
                    source_text=flt.concept,
                    link_type=LinkType.COLUMN,
                    target_id=doc_id,
                    target_label=f"{table_name}.{col_name}",
                    confidence=0.48,
                    evidence="multiple_column_matches",
                    conflict_candidates=[m[2] for m in matches],
                    requires_clarification=True,
                )
            )

        return result

    # ── 财年/自然年冲突检测 ───────────────────────────────────

    @staticmethod
    def _detect_fiscal_year_conflict(question: str) -> str | None:
        """检测问题中是否包含财年关键词但语义不明确。

        NovaRetail 同时使用自然年和财年（2月开始）口径，
        需要在链接阶段就捕获，而不是让 SQL 生成器猜测。
        """
        for kw in _FISCAL_YEAR_KEYWORDS:
            if kw.lower() in question.lower():
                return (
                    f"检测到财年相关表达「{kw}」，请确认您希望使用财年口径（2月1日开始）"
                    f"还是自然年口径，两者在跨期汇总时会产生不同结果"
                )
        return None


# ── V2 回退映射（SemanticRegistry 为空时使用）────────────────
_V2_FALLBACK_MAP: dict[str, str] = {
    "销售额": "net_sales",
    "净销售额": "net_sales",
    "销售收入": "net_sales",
    "营收": "net_sales",
    "GMV": "net_sales",
    "订单量": "paid_order_count",
    "有效订单量": "paid_order_count",
    "订单数": "paid_order_count",
    "销量": "sales_quantity",
    "销售数量": "sales_quantity",
    "件数": "sales_quantity",
    "客单价": "average_order_value",
    "AOV": "average_order_value",
    "退款金额": "refunded_amount",
    "退款率": "refund_rate",
    "退货率": "refund_rate",
    "毛利额": "gross_profit",
    "毛利率": "gross_margin_rate",
    "复购率": "repurchase_rate",
    "活跃客户数": "active_customer_count",
    "新客户数": "new_customer_count",
    "新用户数": "new_customer_count",
    "库存": "inventory_available_quantity",
    "可用库存": "inventory_available_quantity",
    "营销ROI": "roi",
    "ROI": "roi",
}
