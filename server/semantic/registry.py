"""V3 语义指标注册表服务层。

职责：
1. 从 YAML 文件批量导入指标定义（seed 阶段用）
2. 从数据库加载指标注册表，供 SchemaLinker / ContextBuilder 查询
3. 提供统一的 MetricEntry 数据类供上层使用（不暴露 ORM 对象）
4. 负责将 V0 草案 YAML 的指标格式转换为 V3 MetricDefinition 结构

设计约束：
- 指标 ID（metric_id）不以展示名（label）为主键。
- 同义词注册驱动意图链接：用户输入"销售额"→ 找到 metric_id="net_sales"。
- 仅 PUBLISHED 状态的指标才能进入 SQL 生成上下文，DRAFT/TESTING 不对外。
- load_for_query() 返回 active_version 对应的快照内容，而不是草稿。

调用关系：
    SemanticRegistry.load_active_metrics(session)
        → 查询 metric_active_version JOIN metric_version
        → 返回 dict[metric_id, MetricEntry]

    SemanticRegistry.resolve_synonym(text)
        → 在 synonym_map 中查找，返回 metric_id | None

    SemanticRegistry.load_from_yaml(path, session)
        → 批量 upsert MetricDefinition（seed 用）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.semantic.models import (
    MetricActiveVersion,
    MetricDefinition,
    MetricGrain,
    MetricVersion,
    SemanticStatus,
    TimeRole,
    ZeroDenominatorPolicy,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 数据传输对象（不暴露 ORM，供上层使用）
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MetricEntry:
    """已加载的指标定义（来自已发布版本快照或草案）。

    供 SchemaLinker 和 SemanticContextBuilder 使用；
    字段与 MetricDefinition 对应，但来自不可变的版本快照。

    Attributes:
        metric_id: 稳定业务 ID，例如 "net_sales"。
        label: 展示名，例如 "销售额"。
        domain: 所属业务域。
        grain: 聚合粒度。
        expression: SQL 聚合表达式。
        required_filters: 强制过滤条件列表，必须全部注入 SQL。
        dependent_columns: 依赖的物理字段列表。
        allowed_dimensions: 允许分析的维度 ID 列表。
        time_role: 时间归属字段语义。
        zero_denominator_policy: 分母为零的处理策略。
        unit: 单位。
        currency: 币种。
        synonyms: 同义词列表，用于意图链接。
        is_sensitive: 是否敏感（受限权限）。
        time_rule_note: 时间口径说明。
        warning: 使用注意事项。
        version_number: 来自哪个版本快照（0 表示草案，未发布）。
    """

    metric_id: str
    label: str
    domain: str
    grain: str
    expression: str
    required_filters: list[str] = field(default_factory=list)
    dependent_columns: list[str] = field(default_factory=list)
    allowed_dimensions: list[str] = field(default_factory=list)
    time_role: str = "paid_at"
    zero_denominator_policy: str = "not_applicable"
    unit: str | None = None
    currency: str | None = None
    synonyms: list[str] = field(default_factory=list)
    is_sensitive: bool = False
    time_rule_note: str | None = None
    warning: str | None = None
    version_number: int = 0  # 0 = 草案（尚未发布过）

    def to_prompt_dict(self) -> dict[str, Any]:
        """转换为 SQL 生成 Prompt 中可直接注入的字典（只包含生成 SQL 必要的字段）。"""
        result: dict[str, Any] = {
            "id": self.metric_id,
            "label": self.label,
            "grain": self.grain,
            "expression": self.expression,
            "required_filters": self.required_filters,
            "time_role": self.time_role,
            "zero_denominator": self.zero_denominator_policy,
        }
        if self.warning:
            result["warning"] = self.warning
        if self.time_rule_note:
            result["time_rule"] = self.time_rule_note
        if self.unit:
            result["unit"] = self.unit
        return result


# ──────────────────────────────────────────────────────────────
# 注册表服务
# ──────────────────────────────────────────────────────────────


class SemanticRegistry:
    """V3 语义指标注册表。

    实例化后通过 load_active_metrics() 从数据库加载当前发布版本；
    load_from_yaml() 用于 seed 阶段批量写入草案。

    内部维护两个查找表：
    - _metric_map: metric_id → MetricEntry
    - _synonym_map: 同义词 → metric_id（支持多对一映射）
    """

    def __init__(self) -> None:
        self._metric_map: dict[str, MetricEntry] = {}
        self._synonym_map: dict[str, str] = {}

    # ── 查询接口 ──────────────────────────────────────────────

    def get(self, metric_id: str) -> MetricEntry | None:
        """按 ID 查找指标定义。"""
        return self._metric_map.get(metric_id)

    def resolve_synonym(self, text: str) -> str | None:
        """将自然语言文本（可能是同义词）解析为 metric_id。

        先精确匹配同义词表，再尝试用 label 匹配，都找不到返回 None。
        """
        normalized = text.strip()
        # 1. 精确同义词查找
        if normalized in self._synonym_map:
            return self._synonym_map[normalized]
        # 2. label 直接匹配（同义词列表可能没覆盖所有别名）
        for entry in self._metric_map.values():
            if entry.label == normalized:
                return entry.metric_id
        return None

    def all_metrics(self) -> list[MetricEntry]:
        """返回所有已加载的指标定义列表。"""
        return list(self._metric_map.values())

    def metrics_for_domain(self, domain: str) -> list[MetricEntry]:
        """返回指定域的指标列表。"""
        return [e for e in self._metric_map.values() if e.domain == domain]

    def synonym_map(self) -> dict[str, str]:
        """返回完整同义词映射副本（测试/调试用）。"""
        return dict(self._synonym_map)

    # ── 加载接口 ──────────────────────────────────────────────

    async def load_active_metrics(self, session: AsyncSession) -> None:  # pragma: no cover
        """从数据库加载所有指标的当前发布版本快照。

        只加载 PUBLISHED 状态且有 active_version 的指标。
        如果指标无 active_version（从未发布），跳过。
        """
        stmt = (
            select(MetricActiveVersion, MetricVersion)
            .join(
                MetricVersion,
                (MetricActiveVersion.metric_id == MetricVersion.metric_id)
                & (MetricActiveVersion.version_number == MetricVersion.version_number),
            )
        )
        rows = await session.execute(stmt)
        loaded = 0
        for active, version in rows.all():
            try:
                entry = _entry_from_snapshot(active.metric_id, version.version_number, version.snapshot)
                self._register(entry)
                loaded += 1
            except (KeyError, ValueError) as exc:
                logger.warning(
                    "Skipping malformed metric snapshot metric_id=%s version=%s: %s",
                    active.metric_id,
                    version.version_number,
                    exc,
                )
        logger.info("SemanticRegistry loaded %d published metrics from DB", loaded)

    async def load_draft_metrics(self, session: AsyncSession) -> None:  # pragma: no cover
        """加载草案（DRAFT/TESTING）指标，用于开发调试和回归测试。

        注意：草案不应进入生产 SQL 生成上下文，仅供测试用。
        """
        stmt = select(MetricDefinition).where(
            MetricDefinition.status.in_([SemanticStatus.DRAFT, SemanticStatus.TESTING])
        )
        result = await session.execute(stmt)
        loaded = 0
        for (metric,) in result.all():
            entry = _entry_from_orm(metric)
            self._register(entry)
            loaded += 1
        logger.info("SemanticRegistry loaded %d draft metrics from DB", loaded)

    def load_from_entries(self, entries: list[MetricEntry]) -> None:
        """直接从 MetricEntry 列表加载（离线测试/单测用）。"""
        for entry in entries:
            self._register(entry)

    @staticmethod
    def load_from_yaml_no_db(yaml_path: Path) -> "SemanticRegistry":
        """从 YAML 文件直接构造 SemanticRegistry，不需要数据库 Session。

        同时支持 V0 草案格式（semantic_models/drafts/core_metrics.yaml）
        和 V3 扩展格式（semantic_models/v3/metrics.yaml）。
        用于 API 启动时将指标定义加载到内存，无需先写入数据库。

        Args:
            yaml_path: YAML 文件路径。

        Returns:
            已加载指标的 SemanticRegistry 实例。
        """
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid YAML format in {yaml_path}")

        metrics_data = raw.get("metrics", [])
        if not isinstance(metrics_data, list):
            raise ValueError(f"'metrics' key must be a list in {yaml_path}")

        registry = SemanticRegistry()
        entries: list[MetricEntry] = []
        for item in metrics_data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            try:
                entry = _entry_from_yaml_item(item)
                entries.append(entry)
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed metric item id=%s: %s", item.get("id"), exc)

        registry.load_from_entries(entries)
        logger.info("SemanticRegistry loaded %d metrics from %s (no-db)", len(entries), yaml_path)
        return registry

    @staticmethod
    async def seed_from_yaml(yaml_path: Path, session: AsyncSession) -> int:  # pragma: no cover
        """从 YAML 文件批量 upsert MetricDefinition 草案。

        支持 V0 草案格式（semantic_models/drafts/core_metrics.yaml）
        和 V3 扩展格式（semantic_models/v3/metrics.yaml）。

        返回成功 upsert 的指标数量。
        """
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid YAML format in {yaml_path}")

        metrics_data = raw.get("metrics", [])
        if not isinstance(metrics_data, list):
            raise ValueError(f"'metrics' key must be a list in {yaml_path}")

        count = 0
        for item in metrics_data:
            if not isinstance(item, dict):
                continue
            metric_id = item.get("id")
            if not metric_id:
                logger.warning("Skipping metric entry without 'id' in %s", yaml_path)
                continue

            # 检查是否已存在
            existing_result = await session.execute(
                select(MetricDefinition).where(MetricDefinition.metric_id == metric_id)
            )
            existing = existing_result.scalar_one_or_none()

            orm_obj = _yaml_item_to_orm(item, existing)
            if existing is None:
                session.add(orm_obj)
            # 如果已存在，_yaml_item_to_orm 直接修改了 existing 对象，无需 re-add
            count += 1

        await session.flush()
        logger.info("Seeded %d metrics from %s", count, yaml_path)
        return count

    # ── 内部方法 ──────────────────────────────────────────────

    def _register(self, entry: MetricEntry) -> None:
        """注册一个 MetricEntry，同时更新同义词映射。"""
        self._metric_map[entry.metric_id] = entry
        # 将 label 和所有 synonyms 都注册到同义词表
        self._synonym_map[entry.label] = entry.metric_id
        for syn in entry.synonyms:
            if syn in self._synonym_map and self._synonym_map[syn] != entry.metric_id:
                logger.warning(
                    "Synonym conflict: '%s' maps to both '%s' and '%s'; keeping first registration",
                    syn,
                    self._synonym_map[syn],
                    entry.metric_id,
                )
            else:
                self._synonym_map[syn] = entry.metric_id


# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────


def _entry_from_snapshot(metric_id: str, version_number: int, snapshot: dict) -> MetricEntry:
    """从版本快照字典构建 MetricEntry。"""
    return MetricEntry(
        metric_id=metric_id,
        label=snapshot["label"],
        domain=snapshot.get("domain", ""),
        grain=snapshot.get("grain", MetricGrain.PERIOD.value),
        expression=snapshot["expression"],
        required_filters=snapshot.get("required_filters") or [],
        dependent_columns=snapshot.get("dependent_columns") or [],
        allowed_dimensions=snapshot.get("allowed_dimensions") or [],
        time_role=snapshot.get("time_role", TimeRole.PAID_AT.value),
        zero_denominator_policy=snapshot.get(
            "zero_denominator_policy", ZeroDenominatorPolicy.NOT_APPLICABLE.value
        ),
        unit=snapshot.get("unit"),
        currency=snapshot.get("currency"),
        synonyms=snapshot.get("synonyms") or [],
        is_sensitive=snapshot.get("is_sensitive", False),
        time_rule_note=snapshot.get("time_rule_note"),
        warning=snapshot.get("warning"),
        version_number=version_number,
    )


def _entry_from_orm(metric: MetricDefinition) -> MetricEntry:
    """从 ORM 草案对象构建 MetricEntry（version_number=0 表示未发布）。"""
    return MetricEntry(
        metric_id=metric.metric_id,
        label=metric.label,
        domain=metric.domain,
        grain=metric.grain.value if hasattr(metric.grain, "value") else str(metric.grain),
        expression=metric.expression,
        required_filters=metric.required_filters or [],
        dependent_columns=metric.dependent_columns or [],
        allowed_dimensions=metric.allowed_dimensions or [],
        time_role=metric.time_role.value if hasattr(metric.time_role, "value") else str(metric.time_role),
        zero_denominator_policy=(
            metric.zero_denominator_policy.value
            if hasattr(metric.zero_denominator_policy, "value")
            else str(metric.zero_denominator_policy)
        ),
        unit=metric.unit,
        currency=metric.currency,
        synonyms=metric.synonyms or [],
        is_sensitive=metric.is_sensitive,
        time_rule_note=metric.time_rule_note,
        warning=metric.warning,
        version_number=0,
    )


def _yaml_item_to_orm(item: dict, existing: MetricDefinition | None) -> MetricDefinition:
    """将 YAML 条目转换为 MetricDefinition ORM 对象。

    支持 V0 草案字段（zero_denominator、time_rule）和 V3 扩展字段。
    """
    # 字段映射兼容 V0 草案格式
    metric_id: str = item["id"]
    label: str = item.get("label", metric_id)
    domain: str = item.get("domain", _infer_domain(metric_id))
    expression: str = item.get("expression", "")

    # grain 字段兼容
    grain_raw = item.get("grain", "period")
    try:
        grain = MetricGrain(grain_raw)
    except ValueError:
        grain = MetricGrain.PERIOD

    # 强制过滤（V0 格式为字符串列表）
    required_filters: list[str] = item.get("required_filters") or []

    # 同义词
    synonyms: list[str] = item.get("synonyms") or []
    if label not in synonyms:
        synonyms = [label] + synonyms

    # 时间角色（V0 用 time_rule 文字，V3 用 time_role 枚举）
    time_role_raw = item.get("time_role", "paid_at")
    try:
        time_role = TimeRole(time_role_raw)
    except ValueError:
        time_role = TimeRole.PAID_AT

    # 分母策略（V0 用 zero_denominator 字符串）
    zdp_raw = item.get("zero_denominator_policy") or item.get("zero_denominator") or "not_applicable"
    if zdp_raw == "null_with_reason":
        zdp = ZeroDenominatorPolicy.NULL_WITH_REASON
    elif zdp_raw == "zero":
        zdp = ZeroDenominatorPolicy.ZERO
    else:
        zdp = ZeroDenominatorPolicy.NOT_APPLICABLE

    # 敏感度
    is_sensitive = bool(item.get("sensitivity") == "restricted" or item.get("is_sensitive", False))

    # 时间规则说明（V0 格式）
    time_rule_note = item.get("time_rule_note") or item.get("time_rule")

    if existing is not None:
        # Upsert 已有草案：只更新非发布状态的草案字段
        if existing.status in (SemanticStatus.DRAFT, SemanticStatus.TESTING):
            existing.label = label
            existing.domain = domain
            existing.grain = grain
            existing.expression = expression
            existing.required_filters = required_filters
            existing.dependent_columns = item.get("dependent_columns") or []
            existing.allowed_dimensions = item.get("allowed_dimensions") or []
            existing.time_role = time_role
            existing.zero_denominator_policy = zdp
            existing.unit = item.get("unit")
            existing.currency = item.get("currency")
            existing.synonyms = synonyms
            existing.is_sensitive = is_sensitive
            existing.time_rule_note = time_rule_note
            existing.warning = item.get("warning")
        return existing

    return MetricDefinition(
        metric_id=metric_id,
        label=label,
        domain=domain,
        grain=grain,
        expression=expression,
        required_filters=required_filters,
        dependent_columns=item.get("dependent_columns") or [],
        allowed_dimensions=item.get("allowed_dimensions") or [],
        time_role=time_role,
        zero_denominator_policy=zdp,
        unit=item.get("unit"),
        currency=item.get("currency"),
        synonyms=synonyms,
        is_sensitive=is_sensitive,
        time_rule_note=time_rule_note,
        warning=item.get("warning"),
        status=SemanticStatus.DRAFT,
    )


# 按常见的指标命名规则推断所属域（仅当 YAML 未显式指定时使用）
_DOMAIN_KEYWORDS: dict[str, str] = {
    "sales": "sales",
    "order": "sales",
    "refund": "sales",
    "customer": "customer",
    "inventory": "inventory",
    "gross_profit": "finance",
    "gross_margin": "finance",
    "cost": "finance",
    "marketing": "marketing",
    "coupon": "marketing",
    "store": "store",
}


def _infer_domain(metric_id: str) -> str:
    """从 metric_id 关键词推断业务域（后备策略）。"""
    lower = metric_id.lower()
    for keyword, domain in _DOMAIN_KEYWORDS.items():
        if keyword in lower:
            return domain
    return "sales"  # 默认归属销售域


def _entry_from_yaml_item(item: dict) -> MetricEntry:
    """直接从 YAML 字典条目构造 MetricEntry，不经过 ORM。

    兼容 V0 草案格式（zero_denominator、time_rule、sensitivity）
    和 V3 扩展格式（zero_denominator_policy、time_rule_note、is_sensitive）。
    """
    metric_id: str = item["id"]
    label: str = item.get("label", metric_id)
    domain: str = item.get("domain", _infer_domain(metric_id))
    expression: str = item.get("expression", "")

    # grain 兼容
    grain_raw = item.get("grain", "period")
    try:
        grain = MetricGrain(grain_raw).value
    except ValueError:
        grain = "period"

    # 时间角色兼容
    time_role_raw = item.get("time_role", "paid_at")
    try:
        time_role = TimeRole(time_role_raw).value
    except ValueError:
        time_role = "paid_at"

    # 分母策略兼容（V0 用 zero_denominator，V3 用 zero_denominator_policy）
    zdp_raw = (
        item.get("zero_denominator_policy")
        or item.get("zero_denominator")
        or "not_applicable"
    )
    try:
        zdp = ZeroDenominatorPolicy(zdp_raw).value
    except ValueError:
        zdp = "not_applicable"

    # 敏感度（V0 用 sensitivity: restricted，V3 用 is_sensitive: true）
    is_sensitive = bool(
        item.get("sensitivity") == "restricted" or item.get("is_sensitive", False)
    )

    # 同义词（确保 label 本身也在同义词列表里）
    synonyms: list[str] = list(item.get("synonyms") or [])
    if label not in synonyms:
        synonyms = [label] + synonyms

    # 时间规则说明（V0 用 time_rule，V3 用 time_rule_note）
    time_rule_note = item.get("time_rule_note") or item.get("time_rule")

    return MetricEntry(
        metric_id=metric_id,
        label=label,
        domain=domain,
        grain=grain,
        expression=expression,
        required_filters=list(item.get("required_filters") or []),
        dependent_columns=list(item.get("dependent_columns") or []),
        allowed_dimensions=list(item.get("allowed_dimensions") or []),
        time_role=time_role,
        zero_denominator_policy=zdp,
        unit=item.get("unit"),
        currency=item.get("currency"),
        synonyms=synonyms,
        is_sensitive=is_sensitive,
        time_rule_note=time_rule_note,
        warning=item.get("warning"),
        version_number=0,  # YAML 加载视为未发布草案
    )
