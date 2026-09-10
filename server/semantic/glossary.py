"""V3 术语、同义词与维度规则管理服务。

职责：
1. GlossaryService：从数据库加载 BusinessGlossary 和 SemanticDimension，
   提供术语→目标 ID 的查找，供 SchemaLinker 和 ValueLinker 使用。
2. DimensionService：加载维度定义，提供维度 ID 和同义词解析。
3. 将 V2 硬编码的 _ALIAS_DICT 迁移到数据库（YAML seed 辅助函数）。

设计约束：
- 仅 ACTIVE 状态的术语/PUBLISHED 状态的维度进入查询时上下文。
- 同名术语冲突：保留最新版本（updated_at 最大的），并记录警告。
- GlossaryEntry 和 DimensionEntry 是纯 dataclass，不暴露 ORM 对象。

调用关系：
    GlossaryService.load(session) → 内部字典
    GlossaryService.lookup_term(text) → GlossaryEntry | None
    DimensionService.load(session) → 内部字典
    DimensionService.resolve_synonym(text) → dimension_id | None
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.semantic.models import (
    BusinessGlossary,
    GlossaryStatus,
    SemanticDimension,
    SemanticStatus,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 数据传输对象
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GlossaryEntry:
    """已加载的术语词典条目。

    Attributes:
        term: 原始术语文本，例如"销售收入"。
        canonical_target_id: 规范目标 ID，格式 "metric:net_sales" 或 "dimension:region"。
        target_type: "metric" | "dimension" | "value"。
        mapped_value: 如果是值映射，记录实际数据库值，例如 "East China"。
        domain: 适用域。
        owner: 负责人。
        authoritative_source: 权威定义来源。
    """

    term: str
    canonical_target_id: str
    target_type: str
    mapped_value: str | None = None
    domain: str | None = None
    owner: str | None = None
    authoritative_source: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class DimensionEntry:
    """已加载的维度定义条目。

    Attributes:
        dimension_id: 稳定维度 ID，例如 "region"、"city"、"product_category"。
        label: 展示名。
        domain: 所属域。
        dimension_type: time / categorical / hierarchical / geography / customer_segment。
        column_refs: 对应物理列，格式 "table.column"。
        synonyms: 同义词列表。
        hierarchy_levels: 层级路径（仅 HIERARCHICAL 维度）。
    """

    dimension_id: str
    label: str
    domain: str
    dimension_type: str
    column_refs: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    hierarchy_levels: list[str] = field(default_factory=list)
    description: str | None = None


# ──────────────────────────────────────────────────────────────
# 术语服务
# ──────────────────────────────────────────────────────────────


class GlossaryService:
    """业务术语词典服务。

    维护两张查找表：
    - _term_map: term（规范化小写）→ GlossaryEntry
    - _value_map: (column_id, value_text) → mapped_db_value（用于 ValueLinker）
    """

    def __init__(self) -> None:
        self._term_map: dict[str, GlossaryEntry] = {}
        # 值映射：term → (column_ref, db_value)，供 ValueLinker 快速查找
        self._value_alias_map: dict[str, tuple[str, str]] = {}

    async def load(self, session: AsyncSession) -> None:
        """从数据库加载所有 ACTIVE 状态的术语条目。"""
        result = await session.execute(
            select(BusinessGlossary)
            .where(BusinessGlossary.status == GlossaryStatus.ACTIVE)
            .order_by(BusinessGlossary.updated_at.desc())  # 同名取最新
        )
        rows = result.scalars().all()
        loaded = 0
        for row in rows:
            entry = GlossaryEntry(
                term=row.term,
                canonical_target_id=row.canonical_target_id,
                target_type=row.target_type,
                mapped_value=row.mapped_value,
                domain=row.domain,
                owner=row.owner,
                authoritative_source=row.authoritative_source,
                description=row.description,
            )
            norm = row.term.strip().lower()
            if norm in self._term_map:
                logger.debug("Glossary term conflict for '%s'; keeping newer entry", row.term)
            else:
                self._term_map[norm] = entry
                loaded += 1
                # 如果是值映射，同时加入 value_alias_map
                if row.target_type == "value" and row.mapped_value and row.canonical_target_id:
                    self._value_alias_map[norm] = (row.canonical_target_id, row.mapped_value)

        logger.info("GlossaryService loaded %d terms from DB", loaded)

    def load_from_entries(self, entries: list[GlossaryEntry]) -> None:
        """直接从列表加载（离线测试用）。"""
        for entry in entries:
            norm = entry.term.strip().lower()
            self._term_map[norm] = entry
            if entry.target_type == "value" and entry.mapped_value and entry.canonical_target_id:
                self._value_alias_map[norm] = (entry.canonical_target_id, entry.mapped_value)

    def lookup_term(self, text: str) -> GlossaryEntry | None:
        """精确查找术语（不区分大小写）。"""
        return self._term_map.get(text.strip().lower())

    def lookup_value_alias(self, text: str) -> tuple[str, str] | None:
        """查找值别名映射，返回 (column_ref, db_value) 或 None。

        用于 ValueLinker：将"华东"映射到 ("dim_region.region_name", "East China")。
        """
        return self._value_alias_map.get(text.strip().lower())

    def all_entries(self) -> list[GlossaryEntry]:
        return list(self._term_map.values())

    def entries_for_domain(self, domain: str) -> list[GlossaryEntry]:
        return [e for e in self._term_map.values() if e.domain == domain]

    @staticmethod
    async def seed_from_yaml(yaml_path: Path, session: AsyncSession) -> int:  # pragma: no cover
        """从 YAML 批量 upsert BusinessGlossary 条目。

        YAML 格式：
        glossary:
          - term: 华东
            canonical_target_id: dimension:region
            target_type: value
            mapped_value: "East China"
            domain: sales
            owner: 数据分析团队
        """
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid YAML format in {yaml_path}")

        items = raw.get("glossary", [])
        count = 0
        for item in items:
            if not isinstance(item, dict) or not item.get("term"):
                continue

            # 检查是否存在同一 term + target_type 组合
            existing_result = await session.execute(
                select(BusinessGlossary).where(
                    BusinessGlossary.term == item["term"],
                    BusinessGlossary.target_type == item.get("target_type", "metric"),
                )
            )
            existing = existing_result.scalar_one_or_none()

            if existing is not None:
                # 更新现有条目
                existing.canonical_target_id = item.get("canonical_target_id", existing.canonical_target_id)
                existing.mapped_value = item.get("mapped_value")
                existing.domain = item.get("domain")
                existing.owner = item.get("owner")
                existing.authoritative_source = item.get("authoritative_source")
                existing.description = item.get("description")
            else:
                session.add(
                    BusinessGlossary(
                        term=item["term"],
                        canonical_target_id=item.get("canonical_target_id", ""),
                        target_type=item.get("target_type", "metric"),
                        mapped_value=item.get("mapped_value"),
                        domain=item.get("domain"),
                        owner=item.get("owner"),
                        authoritative_source=item.get("authoritative_source"),
                        description=item.get("description"),
                        status=GlossaryStatus.ACTIVE,
                    )
                )
            count += 1

        await session.flush()
        logger.info("Seeded %d glossary entries from %s", count, yaml_path)
        return count


# ──────────────────────────────────────────────────────────────
# 维度服务
# ──────────────────────────────────────────────────────────────


class DimensionService:
    """语义维度服务。

    维护两张查找表：
    - _dimension_map: dimension_id → DimensionEntry
    - _synonym_map: 同义词 → dimension_id
    """

    def __init__(self) -> None:
        self._dimension_map: dict[str, DimensionEntry] = {}
        self._synonym_map: dict[str, str] = {}

    async def load(self, session: AsyncSession) -> None:
        """从数据库加载 PUBLISHED 维度定义。"""
        result = await session.execute(
            select(SemanticDimension).where(
                SemanticDimension.status == SemanticStatus.PUBLISHED
            )
        )
        rows = result.scalars().all()
        for row in rows:
            entry = DimensionEntry(
                dimension_id=row.dimension_id,
                label=row.label,
                domain=row.domain,
                dimension_type=(
                    row.dimension_type.value
                    if hasattr(row.dimension_type, "value")
                    else str(row.dimension_type)
                ),
                column_refs=row.column_refs or [],
                synonyms=row.synonyms or [],
                hierarchy_levels=row.hierarchy_levels or [],
                description=row.description,
            )
            self._register(entry)
        logger.info("DimensionService loaded %d dimensions from DB", len(self._dimension_map))

    def load_draft_dimensions(self, entries: list[DimensionEntry]) -> None:
        """直接从列表加载（离线测试用）。"""
        for entry in entries:
            self._register(entry)

    def get(self, dimension_id: str) -> DimensionEntry | None:
        return self._dimension_map.get(dimension_id)

    def resolve_synonym(self, text: str) -> str | None:
        """将自然语言文本解析为 dimension_id。"""
        normalized = text.strip()
        if normalized in self._synonym_map:
            return self._synonym_map[normalized]
        # label 精确匹配
        for entry in self._dimension_map.values():
            if entry.label == normalized:
                return entry.dimension_id
        return None

    def all_dimensions(self) -> list[DimensionEntry]:
        return list(self._dimension_map.values())

    def dimensions_for_domain(self, domain: str) -> list[DimensionEntry]:
        return [e for e in self._dimension_map.values() if e.domain == domain]

    def synonym_map(self) -> dict[str, str]:
        return dict(self._synonym_map)

    def _register(self, entry: DimensionEntry) -> None:
        self._dimension_map[entry.dimension_id] = entry
        self._synonym_map[entry.label] = entry.dimension_id
        for syn in entry.synonyms:
            if syn not in self._synonym_map:
                self._synonym_map[syn] = entry.dimension_id
            elif self._synonym_map[syn] != entry.dimension_id:
                logger.warning(
                    "Dimension synonym conflict: '%s' maps to both '%s' and '%s'",
                    syn,
                    self._synonym_map[syn],
                    entry.dimension_id,
                )


# ──────────────────────────────────────────────────────────────
# 内置词典数据（从 V2 _ALIAS_DICT 迁移过来的初始值）
# 用于 seed_builtin_glossary() 预填充数据库
# ──────────────────────────────────────────────────────────────

_BUILTIN_GLOSSARY: list[dict] = [
    # ── 区域值映射 ──────────────────────────────
    {"term": "华东", "canonical_target_id": "dim_region.region_name", "target_type": "value", "mapped_value": "East China", "domain": "sales"},
    {"term": "华北", "canonical_target_id": "dim_region.region_name", "target_type": "value", "mapped_value": "North China", "domain": "sales"},
    {"term": "华南", "canonical_target_id": "dim_region.region_name", "target_type": "value", "mapped_value": "South China", "domain": "sales"},
    {"term": "华中", "canonical_target_id": "dim_region.region_name", "target_type": "value", "mapped_value": "Central China", "domain": "sales"},
    {"term": "西南", "canonical_target_id": "dim_region.region_name", "target_type": "value", "mapped_value": "Southwest China", "domain": "sales"},
    {"term": "西北", "canonical_target_id": "dim_region.region_name", "target_type": "value", "mapped_value": "Northwest China", "domain": "sales"},
    {"term": "东北", "canonical_target_id": "dim_region.region_name", "target_type": "value", "mapped_value": "Northeast China", "domain": "sales"},
    # ── 品牌值映射 ──────────────────────────────
    {"term": "苹果", "canonical_target_id": "dim_brand.brand_name", "target_type": "value", "mapped_value": "Apple", "domain": "sales"},
    {"term": "华为", "canonical_target_id": "dim_brand.brand_name", "target_type": "value", "mapped_value": "Huawei", "domain": "sales"},
    {"term": "小米", "canonical_target_id": "dim_brand.brand_name", "target_type": "value", "mapped_value": "Xiaomi", "domain": "sales"},
    # ── 渠道值映射 ──────────────────────────────
    {"term": "线上", "canonical_target_id": "fact_order.channel_type", "target_type": "value", "mapped_value": "ONLINE", "domain": "sales"},
    {"term": "线下", "canonical_target_id": "fact_order.channel_type", "target_type": "value", "mapped_value": "OFFLINE", "domain": "sales"},
    # ── 指标同义词 ──────────────────────────────
    {"term": "GMV", "canonical_target_id": "metric:net_sales", "target_type": "metric", "domain": "sales"},
    {"term": "营收", "canonical_target_id": "metric:net_sales", "target_type": "metric", "domain": "sales"},
    {"term": "销售额", "canonical_target_id": "metric:net_sales", "target_type": "metric", "domain": "sales"},
    {"term": "退货率", "canonical_target_id": "metric:refund_rate", "target_type": "metric", "domain": "sales"},
    {"term": "客单价", "canonical_target_id": "metric:average_order_value", "target_type": "metric", "domain": "sales"},
    {"term": "AOV", "canonical_target_id": "metric:average_order_value", "target_type": "metric", "domain": "sales"},
    {"term": "LTV", "canonical_target_id": "metric:customer_lifetime_value", "target_type": "metric", "domain": "customer"},
    {"term": "ROI", "canonical_target_id": "metric:roi", "target_type": "metric", "domain": "marketing"},
    # ── 维度同义词 ──────────────────────────────
    {"term": "区域", "canonical_target_id": "dimension:region", "target_type": "dimension", "domain": "sales"},
    {"term": "城市", "canonical_target_id": "dimension:city", "target_type": "dimension", "domain": "sales"},
    {"term": "品类", "canonical_target_id": "dimension:product_category", "target_type": "dimension", "domain": "sales"},
    {"term": "渠道", "canonical_target_id": "dimension:channel", "target_type": "dimension", "domain": "sales"},
]


async def seed_builtin_glossary(session: AsyncSession) -> int:  # pragma: no cover
    """将内置词典数据写入 business_glossary 表（幂等）。

    这是 V2 _ALIAS_DICT 到数据库的迁移入口；首次 setup 或 reset 时调用。
    """
    count = 0
    for item in _BUILTIN_GLOSSARY:
        existing_result = await session.execute(
            select(BusinessGlossary).where(
                BusinessGlossary.term == item["term"],
                BusinessGlossary.target_type == item["target_type"],
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is None:
            session.add(
                BusinessGlossary(
                    term=item["term"],
                    canonical_target_id=item["canonical_target_id"],
                    target_type=item["target_type"],
                    mapped_value=item.get("mapped_value"),
                    domain=item.get("domain"),
                    status=GlossaryStatus.ACTIVE,
                )
            )
            count += 1
    await session.flush()
    logger.info("Seeded %d builtin glossary entries", count)
    return count
