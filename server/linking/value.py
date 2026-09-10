"""Value Linking：将用户表达的实体值映射到数据库真实字段值。

问题：用户说"苹果手机"，数据库中存储的是 brand_name='Apple' + category='Smartphone'。
Value Linking 负责把"苹果手机"解析为：
    dim_product.brand_name = 'Apple'   (精确匹配别名字典)
    dim_product.category = 'Smartphone' (别名+语义匹配)

四种匹配策略（优先级从高到低）：
1. 精确匹配（exact_match）：value_text 与 sample_value 完全相等
2. 别名字典（alias_dict）：维护业务实体的中英文别名，例如 {"苹果": "Apple", "华东": "East China"}
3. BM25/模糊匹配（bm25_fuzzy）：通过 SearchRepository.search_values 检索 sample_values
4. 向量回退（vector_fallback）：语义相似性检索，最后手段

输出约定：
- column_id：格式同 document_id.py，例如 "column:1:public:dim_product:brand_name"
- typed_value：已类型化的值，例如 {"type": "string", "value": "Apple"}
- match_evidence：匹配方式，例如 "alias_dict"、"exact_sample_value"

无证据时绝不捏造：如果无法唯一确认一个真实值，返回 requires_clarification=True，
让编排层请求用户澄清，而不是静默注入错误的过滤条件。

调用链：
    ValueLinker.link_values(question, intent, schema_context, repository)
        → 对每个 FilterCondition.value 调用 _link_single_value()
        → 返回 ValueLinkResult
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from server.domain.intent import FilterCondition, QueryIntent
from server.search.repository import Candidate, SearchRepository
from server.search.retrieval import SchemaContext

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 业务别名字典
# 维护常见业务实体的中文表达 → 数据库存储值 的映射
# V3 阶段会迁移到 business_terms 表，V2 先用静态字典
# ──────────────────────────────────────────────
_ALIAS_DICT: dict[str, list[tuple[str, str]]] = {
    # 品牌别名（中文表达 → (列上下文关键词, 数据库真实值)）
    "苹果": [("brand", "Apple"), ("brand_name", "Apple")],
    "苹果手机": [("brand", "Apple"), ("category", "Smartphone")],
    "华为": [("brand", "Huawei"), ("brand_name", "Huawei")],
    "小米": [("brand", "Xiaomi"), ("brand_name", "Xiaomi")],
    # 区域别名（中文 → 英文存储值）
    "华东": [("region", "East China"), ("region_name", "East China")],
    "华南": [("region", "South China"), ("region_name", "South China")],
    "华北": [("region", "North China"), ("region_name", "North China")],
    "华西": [("region", "West China"), ("region_name", "West China")],
    "华中": [("region", "Central China"), ("region_name", "Central China")],
    # 渠道别名
    "线上": [("channel", "online"), ("channel_group", "Online")],
    "线下": [("channel", "offline"), ("channel_group", "Offline")],
}


@dataclass(frozen=True)
class TypedValue:
    """类型化的值映射结果。

    Attributes:
        raw_text: 用户原始表达，例如"苹果手机"。
        column_id: 映射到的列的文档 ID，例如 "column:1:public:dim_product:brand_name"。
        column_label: 列的展示名称，例如 "dim_product.brand_name"。
        value: 数据库中的真实值，例如 "Apple"。
        value_type: 值的数据类型，例如 "string"、"integer"、"date"。
        match_evidence: 匹配方式，例如 "exact_sample"、"alias_dict"、"bm25_fuzzy"。
        confidence: 置信度 0-1。
    """

    raw_text: str
    column_id: str
    column_label: str
    value: str
    value_type: str
    match_evidence: str
    confidence: float


@dataclass
class ValueLinkResult:
    """一条问题所有过滤条件的 Value Linking 结果。

    Attributes:
        typed_values: 已成功链接的类型化值列表（一个用户表达可能映射到多列）。
        unlinked_texts: 无法链接的文本片段。
        requires_clarification: 是否需要向用户确认。
        clarification_prompt: 澄清提示语。
    """

    typed_values: list[TypedValue] = field(default_factory=list)
    unlinked_texts: list[str] = field(default_factory=list)
    requires_clarification: bool = False
    clarification_prompt: str | None = None

    def as_filters(self) -> list[dict[str, str]]:
        """转换为 SQL 过滤条件字典列表，供 Prompt Builder 使用。

        格式：[{"column": "dim_product.brand_name", "value": "Apple"}, ...]
        """
        return [
            {"column": tv.column_label, "value": tv.value, "type": tv.value_type}
            for tv in self.typed_values
        ]


class ValueLinker:
    """将用户表达的实体值映射到数据库真实值。

    Args:
        alias_dict: 业务别名字典，默认使用内置的 _ALIAS_DICT。
        confidence_threshold: 低于此置信度的结果加入 unlinked。
    """

    def __init__(
        self,
        alias_dict: dict[str, list[tuple[str, str]]] | None = None,
        confidence_threshold: float = 0.7,
    ) -> None:
        self._alias_dict = alias_dict or _ALIAS_DICT
        self._threshold = confidence_threshold

    async def link_values(
        self,
        intent: QueryIntent,
        schema_context: SchemaContext,
        repository: SearchRepository,
        *,
        datasource_id: int,
    ) -> ValueLinkResult:
        """对所有过滤条件执行 Value Linking。

        Args:
            intent: 含 filters 的意图结构。
            schema_context: 两级召回结果，用于确认列是否在候选范围内。
            repository: 检索仓储，用于 BM25/fuzzy 回退。
            datasource_id: 数据源 ID。
        """
        typed_values: list[TypedValue] = []
        unlinked: list[str] = []

        for flt in intent.filters:
            results = await self._link_single_value(
                flt, schema_context, repository, datasource_id=datasource_id
            )
            if results:
                typed_values.extend(results)
            else:
                unlinked.append(flt.value)

        requires_clarification = bool(unlinked)
        clarification = None
        if unlinked:
            clarification = (
                f"无法确认以下实体值对应的数据：{'、'.join(unlinked)}，"
                "请您提供更精确的名称或选择选项。"
            )

        return ValueLinkResult(
            typed_values=typed_values,
            unlinked_texts=unlinked,
            requires_clarification=requires_clarification,
            clarification_prompt=clarification,
        )

    async def _link_single_value(
        self,
        flt: FilterCondition,
        schema_context: SchemaContext,
        repository: SearchRepository,
        *,
        datasource_id: int,
    ) -> list[TypedValue]:
        """对单个过滤条件执行多策略值链接。"""
        value_text = flt.value

        # 策略 1：别名字典精确匹配
        alias_results = self._try_alias_dict(value_text, schema_context)
        if alias_results:
            return alias_results

        # 策略 2：在 sample_values 中精确检索
        exact_results = self._try_exact_sample_match(value_text, schema_context)
        if exact_results:
            return exact_results

        # 策略 3：BM25/fuzzy 检索（通过 SearchRepository.search_values）
        search_result = await repository.search_values(
            value_text,
            datasource_id=datasource_id,
            allowed_domains=list(intent_domains_from_context(schema_context)),
        )
        bm25_results = self._parse_value_search_results(value_text, search_result.candidates)
        if bm25_results:
            return bm25_results

        # 策略 4：没有找到任何匹配
        logger.debug("Value Linking: no match found for '%s'", value_text)
        return []

    def _try_alias_dict(self, value_text: str, schema_context: SchemaContext) -> list[TypedValue]:
        """从别名字典中查找映射，并与候选列交叉验证。

        对于"苹果手机"这类多词实体，一次可能产生多个 TypedValue：
        brand_name='Apple' + category='Smartphone'。
        """
        aliases = self._alias_dict.get(value_text)
        if not aliases:
            return []

        results: list[TypedValue] = []
        # 构建候选列的快速查找字典：column_name → (table_name, doc_id)
        col_index: dict[str, tuple[str, str]] = {}
        for col in schema_context.columns:
            col_name = col.payload.get("column_name", "")
            table_name = col.payload.get("table_name", "")
            if col_name:
                col_index[col_name] = (table_name, col.doc_id)

        for col_keyword, db_value in aliases:
            # 查找候选列中是否有名称包含 col_keyword 的列
            matched_col = None
            for col_name, (table_name, doc_id) in col_index.items():
                if col_keyword in col_name:
                    matched_col = (col_name, table_name, doc_id)
                    break

            if matched_col:
                col_name, table_name, doc_id = matched_col
                results.append(
                    TypedValue(
                        raw_text=value_text,
                        column_id=doc_id,
                        column_label=f"{table_name}.{col_name}",
                        value=db_value,
                        value_type="string",
                        match_evidence="alias_dict",
                        confidence=0.9,
                    )
                )

        return results

    def _try_exact_sample_match(
        self, value_text: str, schema_context: SchemaContext
    ) -> list[TypedValue]:
        """在候选列的 sample_values 中精确查找。

        sample_values 存储 JSON 数组字符串，例如 '["Apple", "Huawei", "Xiaomi"]'。
        """
        import json

        results: list[TypedValue] = []
        for col in schema_context.columns:
            sample_values_raw = col.payload.get("sample_values")
            if not sample_values_raw:
                continue
            try:
                samples = json.loads(sample_values_raw)
                if not isinstance(samples, list):
                    continue
            except (json.JSONDecodeError, TypeError):
                continue

            # 精确匹配（大小写不敏感）
            matched_val = next(
                (sv for sv in samples if str(sv).lower() == value_text.lower()),
                None,
            )
            if matched_val:
                table_name = col.payload.get("table_name", "")
                col_name = col.payload.get("column_name", "")
                results.append(
                    TypedValue(
                        raw_text=value_text,
                        column_id=col.doc_id,
                        column_label=f"{table_name}.{col_name}",
                        value=str(matched_val),
                        value_type=_infer_value_type(col.payload.get("data_type", "text")),
                        match_evidence="exact_sample_value",
                        confidence=0.95,
                    )
                )
        return results

    def _parse_value_search_results(
        self,
        value_text: str,
        candidates: list[Candidate],
    ) -> list[TypedValue]:
        """将 search_values 的候选结果转换为 TypedValue。"""

        results: list[TypedValue] = []
        for c in candidates:
            if c.score < self._threshold:
                continue
            table_name = c.payload.get("table_name", "")
            col_name = c.payload.get("column_name", "")
            results.append(
                TypedValue(
                    raw_text=value_text,
                    column_id=c.doc_id,
                    column_label=f"{table_name}.{col_name}",
                    value=value_text,  # BM25 只能确认列，值使用原始文本
                    value_type=_infer_value_type(c.payload.get("data_type", "text")),
                    match_evidence="bm25_fuzzy",
                    confidence=min(c.score, 0.85),
                )
            )
        return results


def _infer_value_type(data_type: str) -> str:
    """根据数据库字段类型推断值类型，用于 SQL 参数化。"""
    dt = data_type.lower()
    if any(t in dt for t in ("int", "serial", "bigint", "smallint")):
        return "integer"
    if any(t in dt for t in ("numeric", "decimal", "float", "double")):
        return "number"
    if any(t in dt for t in ("date", "timestamp")):
        return "date"
    if any(t in dt for t in ("bool",)):
        return "boolean"
    return "string"


def intent_domains_from_context(schema_context: SchemaContext) -> set[str]:
    """从 SchemaContext 中提取所有涉及的业务域。"""
    return {c.domain for c in schema_context.tables if c.domain}
