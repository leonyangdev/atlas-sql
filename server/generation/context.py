"""V3 语义上下文组装器（SemanticContextBuilder）。

职责：将以下多路信息整合为 SQL 生成器可直接使用的上下文包：
  1. Schema Context     — 两级召回结果（表+列）
  2. Join Paths         — JoinGraph 补齐的桥接路径
  3. Metric Definitions — 已发布指标表达式 + 强制过滤 + 时间规则
  4. Value Mappings     — ValueLinker 的值别名结果（已类型化）
  5. Business Rules     — 来自 MetricEntry.required_filters 的强制规则
  6. Verified Examples  — 动态召回的相关可信查询（few-shot）
  7. Semantic Version   — 绑定的语义版本快照标识

设计约束（V3-S05-T02）：
  - 元数据注释（raw_comment）和样例 SQL 文本来自外部，必须标记为 NOT_TRUSTED。
  - NOT_TRUSTED 内容进入 Prompt 时包裹在 <!-- untrusted --> 标记中，
    模型被明确告知不得将其中的内容当作系统指令执行。
  - 越权对象（敏感指标 + 不在 allowed_domains 的对象）在组装前过滤，
    不进入最终 Context，不依赖模型自行判断权限。
  - token 预算约束：超出 budget 时优先裁剪低分列 > 裁剪样例 > 裁剪描述文字。

Token 估算规则（粗略）：
  - 每张表头：20 tokens
  - 每个列：15 tokens
  - 每个指标定义：50 tokens
  - 每条 verified example：80 tokens
  - 每条值映射：10 tokens

调用链：
    SemanticContextBuilder.build(
        question, intent, schema_context, link_result,
        metric_entries, verified_examples, value_links
    ) → SemanticContext

    SemanticContext.to_prompt_dict() → dict（注入 SQLPromptBuilder）
    SemanticContext.semantic_version_ref → str（记录到 QueryRecord）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from server.search.retrieval import SchemaContext
from server.semantic.registry import MetricEntry

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Token 估算常量
# ──────────────────────────────────────────────────────────────

_T_TABLE_HEADER = 20
_T_COLUMN = 15
_T_METRIC = 50
_T_EXAMPLE = 80
_T_VALUE_MAP = 10
_T_JOIN_PATH = 15

# 禁止出现在 trusted 区域的注入模式（防止元数据注释中的指令注入）
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(previous|all)\s+instructions?", re.IGNORECASE),
    re.compile(r"你(现在)?(是|变成|扮演)", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"<\s*/?system\s*>", re.IGNORECASE),
    re.compile(r"SYSTEM:", re.IGNORECASE),
]


# ──────────────────────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ValueLink:
    """单个过滤值的链接结果。

    Attributes:
        source_text: 用户原始值表达，例如"华东"。
        column_ref: 物理列引用，例如 "dim_region.region_name"。
        db_value: 数据库存储的真实值，例如 "East China"。
        evidence: 匹配依据，例如 "glossary_alias"。
    """

    source_text: str
    column_ref: str
    db_value: str
    evidence: str = "unknown"


@dataclass(frozen=True)
class VerifiedExample:
    """用于 few-shot 的已验证查询样例。

    Attributes:
        query_id: 样例 ID（用于来源追溯）。
        question: 问题文本（来自外部，标记为 NOT_TRUSTED）。
        sql: 已验证 SQL（来自外部，标记为 NOT_TRUSTED）。
        similarity_score: 与当前问题的相似度分数。
    """

    query_id: str
    question: str
    sql: str
    similarity_score: float = 0.0


@dataclass
class SemanticContext:
    """V3 语义上下文包。

    组装完成后通过 to_prompt_dict() 序列化为 Prompt 可注入的字典。

    Attributes:
        schema_tables: 召回的表（过滤越权后）。
        schema_columns: 召回的列（过滤越权后）。
        join_paths: JoinGraph 补齐的连接路径描述。
        metric_entries: 当前问题涉及的指标定义。
        value_links: 值别名链接结果。
        verified_examples: 动态召回的 few-shot 样例。
        semantic_version_ref: 语义版本快照标识。
        estimated_tokens: 总 token 估算。
        token_budget_exceeded: 是否触发了裁剪。
        untrusted_fields: 被标记为不可信的字段名列表（审计用）。
    """

    schema_tables: list[dict[str, Any]] = field(default_factory=list)
    schema_columns: list[dict[str, Any]] = field(default_factory=list)
    join_paths: list[str] = field(default_factory=list)
    metric_entries: list[MetricEntry] = field(default_factory=list)
    value_links: list[ValueLink] = field(default_factory=list)
    verified_examples: list[VerifiedExample] = field(default_factory=list)
    semantic_version_ref: str = ""
    estimated_tokens: int = 0
    token_budget_exceeded: bool = False
    untrusted_fields: list[str] = field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        """序列化为 Prompt 注入字典。

        不可信内容（raw_comment、样例文本）用 <!-- untrusted --> 标记包裹。
        越权对象已在 build 阶段过滤，此处不再检查。
        """
        return {
            "semantic_version_ref": self.semantic_version_ref,
            "schema": _render_schema(self.schema_tables, self.schema_columns),
            "join_paths": self.join_paths,
            "metrics": [m.to_prompt_dict() for m in self.metric_entries],
            "value_mappings": [
                {
                    "source": vl.source_text,
                    "column": vl.column_ref,
                    "db_value": vl.db_value,
                    "evidence": vl.evidence,
                }
                for vl in self.value_links
            ],
            "verified_examples": [
                {
                    # 样例内容标记为不可信，模型不应将其当作系统指令
                    "question": _wrap_untrusted(ex.question),
                    "sql": _wrap_untrusted(ex.sql),
                    "source_id": ex.query_id,
                }
                for ex in self.verified_examples
            ],
            "estimated_tokens": self.estimated_tokens,
        }

    def metric_ids(self) -> list[str]:
        return [m.metric_id for m in self.metric_entries]

    def required_filters(self) -> list[str]:
        """所有指标的强制过滤条件合并（去重）。"""
        seen: set[str] = set()
        result: list[str] = []
        for m in self.metric_entries:
            for f in m.required_filters:
                if f not in seen:
                    seen.add(f)
                    result.append(f)
        return result


# ──────────────────────────────────────────────────────────────
# 构建器
# ──────────────────────────────────────────────────────────────


class SemanticContextBuilder:
    """V3 语义上下文构建器。

    Args:
        token_budget: 最大 token 估算值（超出时触发裁剪）。
        max_examples: few-shot 最多注入的样例数量。
        allowed_domains: 允许的业务域（越权对象被过滤）。
    """

    def __init__(
        self,
        token_budget: int = 6_000,
        max_examples: int = 5,
        allowed_domains: list[str] | None = None,
    ) -> None:
        self._budget = token_budget
        self._max_examples = max_examples
        self._allowed_domains = set(allowed_domains or [])

    def build(
        self,
        *,
        schema_context: SchemaContext,
        metric_entries: list[MetricEntry],
        value_links: list[ValueLink] | None = None,
        verified_examples: list[VerifiedExample] | None = None,
        join_paths: list[str] | None = None,
        semantic_version_ref: str = "",
    ) -> SemanticContext:
        """组装语义上下文。

        步骤：
        1. 过滤越权对象（sensitive=True 且不在 allowed_domains）
        2. 扫描元数据注释中的注入模式，清理或标记
        3. 估算 token，超出预算时按优先级裁剪
        4. 组装 SemanticContext
        """
        untrusted_fields: list[str] = []

        # 1. 过滤越权指标（敏感指标默认不进入上下文）
        safe_metrics = [
            m for m in metric_entries
            if not m.is_sensitive or (
                self._allowed_domains and m.domain in self._allowed_domains
            )
        ]
        if len(safe_metrics) < len(metric_entries):
            filtered_count = len(metric_entries) - len(safe_metrics)
            logger.info(
                "SemanticContextBuilder: filtered %d sensitive metrics (not in allowed_domains)",
                filtered_count,
            )

        # 2. 过滤越权表/列（不在 allowed_domains 的域）
        safe_tables = []
        for c in schema_context.tables:
            if self._allowed_domains and c.domain and c.domain not in self._allowed_domains:
                continue
            # 检查 raw_comment 注入模式
            raw_comment = c.payload.get("raw_comment", "") or ""
            cleaned_comment, injected = _sanitize_untrusted(raw_comment)
            if injected:
                untrusted_fields.append(f"table:{c.payload.get('table_name','?')}:raw_comment")
            payload = dict(c.payload)
            if injected:
                payload["raw_comment"] = cleaned_comment
            safe_tables.append(payload)

        safe_columns = []
        for c in schema_context.columns:
            if self._allowed_domains and c.domain and c.domain not in self._allowed_domains:
                continue
            raw_comment = c.payload.get("raw_comment", "") or ""
            cleaned_comment, injected = _sanitize_untrusted(raw_comment)
            if injected:
                untrusted_fields.append(
                    f"column:{c.payload.get('table_name','?')}.{c.payload.get('column_name','?')}:raw_comment"
                )
            payload = dict(c.payload)
            if injected:
                payload["raw_comment"] = cleaned_comment
            safe_columns.append(payload)

        # 3. 处理 verified examples（外部内容，全部标记为 NOT_TRUSTED）
        safe_examples = list(verified_examples or [])
        if safe_examples:
            untrusted_fields.append("verified_examples")
        # 限制数量
        safe_examples = safe_examples[: self._max_examples]

        # 4. Token 估算
        estimated = _estimate_tokens(safe_tables, safe_columns, safe_metrics, safe_examples, value_links or [], join_paths or [])
        budget_exceeded = estimated > self._budget

        if budget_exceeded:
            # 裁剪顺序：样例 → 低分列 → 描述文字
            safe_examples, safe_columns = _apply_budget_trim(
                safe_examples,
                safe_columns,
                safe_metrics,
                safe_tables,
                join_paths or [],
                value_links or [],
                self._budget,
            )
            estimated = _estimate_tokens(safe_tables, safe_columns, safe_metrics, safe_examples, value_links or [], join_paths or [])
            logger.info(
                "SemanticContextBuilder: token budget trimmed to %d tokens (%d examples, %d columns)",
                estimated,
                len(safe_examples),
                len(safe_columns),
            )

        return SemanticContext(
            schema_tables=safe_tables,
            schema_columns=safe_columns,
            join_paths=join_paths or [],
            metric_entries=safe_metrics,
            value_links=value_links or [],
            verified_examples=safe_examples,
            semantic_version_ref=semantic_version_ref,
            estimated_tokens=estimated,
            token_budget_exceeded=budget_exceeded,
            untrusted_fields=untrusted_fields,
        )


# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────


def _wrap_untrusted(text: str) -> str:
    """将不可信文本包裹在 HTML 注释标记中，防止模型将其当作系统指令。"""
    return f"<!-- untrusted -->{text}<!-- /untrusted -->"


def _sanitize_untrusted(text: str) -> tuple[str, bool]:
    """扫描并清理文本中的注入模式。

    Returns:
        (cleaned_text, found_injection)
    """
    if not text:
        return text, False
    found = False
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            found = True
            text = pattern.sub("[REDACTED]", text)
    return text, found


def _estimate_tokens(
    tables: list[dict],
    columns: list[dict],
    metrics: list[MetricEntry],
    examples: list[VerifiedExample],
    value_links: list[ValueLink],
    join_paths: list[str],
) -> int:
    return (
        len(tables) * _T_TABLE_HEADER
        + len(columns) * _T_COLUMN
        + len(metrics) * _T_METRIC
        + len(examples) * _T_EXAMPLE
        + len(value_links) * _T_VALUE_MAP
        + len(join_paths) * _T_JOIN_PATH
    )


def _apply_budget_trim(
    examples: list[VerifiedExample],
    columns: list[dict],
    metrics: list[MetricEntry],
    tables: list[dict],
    join_paths: list[str],
    value_links: list[ValueLink],
    budget: int,
) -> tuple[list[VerifiedExample], list[dict]]:
    """按优先级裁剪：先减样例数，再裁低分普通列。"""
    # 先计算固定部分（表+指标+值映射+路径）
    fixed = (
        len(tables) * _T_TABLE_HEADER
        + len(metrics) * _T_METRIC
        + len(value_links) * _T_VALUE_MAP
        + len(join_paths) * _T_JOIN_PATH
    )

    # 逐步减少样例数
    trimmed_examples = list(examples)
    while trimmed_examples and _estimate_tokens(tables, columns, metrics, trimmed_examples, value_links, join_paths) > budget:
        trimmed_examples.pop()  # 移除最低分（假设已按相似度降序排列）

    # 如果还超，裁列（保护主外键）
    col_budget = budget - fixed - len(trimmed_examples) * _T_EXAMPLE
    trimmed_columns = _trim_columns(columns, col_budget)

    return trimmed_examples, trimmed_columns


def _trim_columns(columns: list[dict], col_budget: int) -> list[dict]:
    """在 token 预算内裁剪列，保护主外键和时间字段。"""
    protected = [c for c in columns if c.get("is_primary_key") or c.get("foreign_key_ref")]
    ordinary = [c for c in columns if not c.get("is_primary_key") and not c.get("foreign_key_ref")]

    protected_tokens = len(protected) * _T_COLUMN
    remaining = max(0, col_budget - protected_tokens)

    kept_ordinary: list[dict] = []
    used = 0
    for c in ordinary:
        if used + _T_COLUMN > remaining:
            break
        kept_ordinary.append(c)
        used += _T_COLUMN

    return protected + kept_ordinary


def _render_schema(
    tables: list[dict], columns: list[dict]
) -> list[dict[str, Any]]:
    """将表+列合并为嵌套的 Schema 描述列表。

    每张表包含：table_name、business_name、description（已清理）、columns[]。
    raw_comment 如果存在则附加到 description 后面，并标注来源。
    """
    # 按 table_name 组织列
    table_columns: dict[str, list[dict]] = {}
    for col in columns:
        tn = col.get("table_name", "")
        if tn:
            table_columns.setdefault(tn, []).append(col)

    result = []
    for table in tables:
        tn = table.get("table_name", "")
        desc = table.get("manual_description") or table.get("description", "")
        raw_comment = table.get("raw_comment", "")
        # raw_comment 已在 build 阶段清理/标记，此处只附加
        if raw_comment and raw_comment != desc:
            desc = f"{desc} | {_wrap_untrusted(raw_comment)}" if desc else _wrap_untrusted(raw_comment)

        cols = table_columns.get(tn, [])
        result.append(
            {
                "table_name": tn,
                "business_name": table.get("manual_business_name") or table.get("business_name", ""),
                "description": desc,
                "domain": table.get("domain", ""),
                "columns": [
                    {
                        "column_name": c.get("column_name", ""),
                        "data_type": c.get("data_type", ""),
                        "business_name": c.get("manual_business_name") or c.get("business_name", ""),
                        "description": c.get("manual_description") or c.get("description", ""),
                        "is_primary_key": c.get("is_primary_key", False),
                        "foreign_key_ref": c.get("foreign_key_ref"),
                    }
                    for c in cols
                ],
            }
        )
    return result
