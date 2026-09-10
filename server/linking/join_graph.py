"""Join Graph：从 PostgreSQL 关系定义构建内存图，支持路径搜索和粒度保护。

设计原则（V2 约定）：
- 不引入 Neo4j 等图数据库；关系定义存 PostgreSQL，加载后在内存中用邻接表表示有向图。
- 边记录 join_keys（连接键对）、direction（多对一/一对多）、cardinality、用途标记。
- 路径搜索使用 BFS（最短路径），路径有歧义时触发澄清，不静默选择。
- 基数检查：多事实直接 JOIN 不因"键存在"自动获准，需要显式标注 requires_pre_aggregation=True。
- 扇出风险（fan-out）：多对多或多事实 JOIN 会标注警告，供 SQL Generator 决定是否预聚合。

ORM 模型 TableRelationship 存储在控制库，由元数据采集阶段从外键和人工注释填入。

调用链：
    JoinGraph.load_from_db(session)         # 从数据库加载关系定义
    JoinGraph.find_paths(source, target)    # 寻找两表间的合法路径
    JoinGraph.validate_path(path)           # 校验路径的基数和扇出风险
    JoinGraph.complete_schema(selected_tables) # 补齐桥接表
"""

from __future__ import annotations

import enum
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from server.db import Base

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# ORM 模型：表关系定义
# ──────────────────────────────────────────────


class RelationshipCardinality(enum.StrEnum):
    """JOIN 关系的基数类型。"""

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"  # 左表一行对应右表多行（通常是维度 → 事实）
    MANY_TO_ONE = "many_to_one"  # 左表多行对应右表一行（通常是事实 → 维度）
    MANY_TO_MANY = "many_to_many"  # 需要桥接表，直接 JOIN 会扇出


class RelationshipPurpose(enum.StrEnum):
    """关系的业务用途，决定检索时是否允许使用该边。"""

    JOIN = "join"  # 正常 JOIN 路径
    LOOKUP = "lookup"  # 只用于维度查找，不用于聚合
    AGGREGATE_JOIN = "agg_join"  # 必须预聚合才能使用的关联
    BRIDGE = "bridge"  # 纯桥接表，不携带业务含义


class TableRelationship(Base):
    """表与表之间的关系定义（存储在控制库）。

    Attributes:
        from_table: 源表名称（不含 schema，schema 通过 datasource_id 隐含）。
        to_table: 目标表名称。
        from_column: 源表的连接键列名。
        to_column: 目标表的连接键列名。
        cardinality: 关系基数（多对一、一对多等）。
        purpose: 关系的业务用途（JOIN / LOOKUP / BRIDGE）。
        is_active: False 时表示该关系已废弃，图构建时跳过。
        valid_from / valid_to: 关系的有效期（用于历史快照表的时间条件）。
        description: 人工注释的关系说明。
    """

    __tablename__ = "table_relationship"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datasource_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("datasource.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_table: Mapped[str] = mapped_column(String(128), nullable=False)
    to_table: Mapped[str] = mapped_column(String(128), nullable=False)
    from_column: Mapped[str] = mapped_column(String(128), nullable=False)
    to_column: Mapped[str] = mapped_column(String(128), nullable=False)
    cardinality: Mapped[RelationshipCardinality] = mapped_column(
        Enum(RelationshipCardinality, name="relationship_cardinality"),
        nullable=False,
        insert_default=RelationshipCardinality.MANY_TO_ONE,
    )
    purpose: Mapped[RelationshipPurpose] = mapped_column(
        Enum(RelationshipPurpose, name="relationship_purpose"),
        nullable=False,
        insert_default=RelationshipPurpose.JOIN,
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ──────────────────────────────────────────────
# 内存图数据结构
# ──────────────────────────────────────────────


@dataclass(frozen=True)
class GraphEdge:
    """内存图的有向边，表示两张表之间的 JOIN 关系。"""

    from_table: str
    to_table: str
    from_column: str
    to_column: str
    cardinality: RelationshipCardinality
    purpose: RelationshipPurpose
    relationship_id: int  # 对应 TableRelationship.id，用于溯源

    @property
    def is_many_to_many(self) -> bool:
        return self.cardinality == RelationshipCardinality.MANY_TO_MANY

    @property
    def requires_pre_aggregation(self) -> bool:
        """多对多关系或 agg_join 用途的关系，必须预聚合才能使用。"""
        return (
            self.cardinality == RelationshipCardinality.MANY_TO_MANY
            or self.purpose == RelationshipPurpose.AGGREGATE_JOIN
        )


@dataclass
class JoinPath:
    """两表之间的 JOIN 路径。

    Attributes:
        tables: 路径经过的所有表，包括起点和终点。
        edges: 路径经过的所有边。
        has_fan_out_risk: 路径中包含多对多关系或多事实直接 JOIN 风险。
        requires_pre_aggregation: 路径中存在需要预聚合的关联。
        missing_tables: 补齐路径后需要额外添加的桥接表。
        warning: 路径风险说明（供调试和 Trace 使用）。
    """

    tables: list[str] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    has_fan_out_risk: bool = False
    requires_pre_aggregation: bool = False
    missing_tables: list[str] = field(default_factory=list)
    warning: str | None = None

    @property
    def is_valid(self) -> bool:
        """路径有效的定义：存在路径 + 不需要预聚合（或已知风险）。"""
        return bool(self.tables) and not self.requires_pre_aggregation


@dataclass
class JoinGraphResult:
    """complete_schema() 的返回值。"""

    # 补齐后的完整表列表（原始 selected_tables + 补全的桥接表）
    complete_tables: list[str] = field(default_factory=list)
    # 每对 (source, target) 的最优路径
    paths: dict[tuple[str, str], JoinPath] = field(default_factory=dict)
    # 需要预聚合的表对（多事实直接 JOIN）
    pre_aggregation_required: list[tuple[str, str]] = field(default_factory=list)
    # 无法找到路径的表对
    missing_paths: list[tuple[str, str]] = field(default_factory=list)
    # 是否需要向用户澄清（路径歧义或多事实 JOIN）
    requires_clarification: bool = False
    clarification_prompt: str | None = None


class JoinGraph:
    """基于 PostgreSQL 关系定义的内存有向图，提供路径搜索和粒度保护。

    加载方式：
        JoinGraph.load_from_records(relationships)  # 从 ORM 对象列表加载（测试友好）

    主要方法：
        find_paths(source, target)     → list[JoinPath]（可能有多条）
        complete_schema(tables)        → JoinGraphResult（补齐桥接表）
        check_fan_out(tables)          → list[str]（有扇出风险的表对说明）
    """

    def __init__(self) -> None:
        # 邻接表：from_table → list[GraphEdge]
        self._adj: dict[str, list[GraphEdge]] = {}
        # 所有表名（节点集合）
        self._nodes: set[str] = set()

    @classmethod
    def load_from_records(cls, relationships: list[TableRelationship]) -> JoinGraph:
        """从 ORM 对象列表构建内存图。

        只加载 is_active=True 的关系，忽略已废弃的关系。
        双向边（A→B 和 B→A）由 from/to 的不同记录独立控制，不自动添加反向边。
        """
        graph = cls()
        for rel in relationships:
            if not rel.is_active:
                continue
            edge = GraphEdge(
                from_table=rel.from_table,
                to_table=rel.to_table,
                from_column=rel.from_column,
                to_column=rel.to_column,
                cardinality=rel.cardinality,
                purpose=rel.purpose,
                relationship_id=rel.id,
            )
            graph._adj.setdefault(rel.from_table, []).append(edge)
            graph._nodes.add(rel.from_table)
            graph._nodes.add(rel.to_table)
        return graph

    def find_paths(
        self,
        source: str,
        target: str,
        max_depth: int = 5,
    ) -> list[JoinPath]:
        """BFS 搜索从 source 到 target 的所有最短路径（不超过 max_depth 跳）。

        Returns:
            按路径长度升序的路径列表。空列表表示不可达。
        """
        if source == target:
            return [JoinPath(tables=[source], edges=[])]

        if source not in self._nodes or target not in self._nodes:
            return []

        # BFS，记录 (当前表, 经过的表列表, 经过的边列表)
        queue: deque[tuple[str, list[str], list[GraphEdge]]] = deque()
        queue.append((source, [source], []))
        visited_at_depth: dict[str, int] = {source: 0}
        found_paths: list[JoinPath] = []
        shortest_len: int | None = None

        while queue:
            current, path, edges = queue.popleft()

            if len(path) > max_depth + 1:
                continue

            # 找到目标
            if current == target:
                path_obj = self._build_path(path, edges)
                found_paths.append(path_obj)
                if shortest_len is None:
                    shortest_len = len(path)
                # 只返回最短等长路径
                continue

            # 剪枝：已经找到路径且当前深度超过最短路径
            if shortest_len is not None and len(path) >= shortest_len:
                continue

            # 扩展邻居
            for edge in self._adj.get(current, []):
                if edge.purpose == RelationshipPurpose.BRIDGE:
                    # BRIDGE 边可以作为中间节点，但不作为终点
                    pass
                neighbor = edge.to_table
                depth = len(path)
                # 避免重复访问同一节点（允许在不同深度再次访问，但不超过最短路径深度）
                if neighbor in visited_at_depth and visited_at_depth[neighbor] < depth:
                    continue
                visited_at_depth[neighbor] = depth
                queue.append((neighbor, path + [neighbor], edges + [edge]))

        return sorted(found_paths, key=lambda p: len(p.tables))

    def complete_schema(
        self,
        selected_tables: list[str],
    ) -> JoinGraphResult:
        """给定初步选中的表，补齐必要的桥接表，检查多事实扇出风险。

        例如：selected_tables = ["fact_order_item", "dim_region"]
        路径：fact_order_item → fact_order → dim_store → dim_city → dim_region
        补齐后：["fact_order_item", "dim_region", "fact_order", "dim_store", "dim_city"]

        Args:
            selected_tables: Schema Linking 后选中的表（不含中间表）。

        Returns:
            JoinGraphResult，包含完整表列表和路径信息。
        """
        if len(selected_tables) <= 1:
            return JoinGraphResult(complete_tables=list(selected_tables))

        paths: dict[tuple[str, str], JoinPath] = {}
        missing: list[tuple[str, str]] = []
        pre_agg_required: list[tuple[str, str]] = []
        bridge_tables: set[str] = set()

        # 对每对表寻找路径
        for i, src in enumerate(selected_tables):
            for tgt in selected_tables[i + 1 :]:
                found = self.find_paths(src, tgt)
                if not found:
                    # 尝试反向
                    found_rev = self.find_paths(tgt, src)
                    if found_rev:
                        found = found_rev
                if not found:
                    missing.append((src, tgt))
                    continue

                best_path = found[0]  # 最短路径
                paths[(src, tgt)] = best_path

                # 收集桥接表（路径中不在 selected_tables 里的中间表）
                for t in best_path.tables:
                    if t not in selected_tables:
                        bridge_tables.add(t)

                if best_path.requires_pre_aggregation:
                    pre_agg_required.append((src, tgt))

        # 构建完整表列表
        complete = list(selected_tables) + sorted(bridge_tables)

        # 检查多事实扇出
        fact_tables = [t for t in selected_tables if t.startswith("fact_")]
        fan_out_warning = None
        if len(fact_tables) > 1:
            fan_out_warning = (
                f"多事实表直接 JOIN 存在扇出风险：{', '.join(fact_tables)}。"
                "请确认是否需要先对各事实表预聚合再 JOIN。"
            )
            logger.warning(fan_out_warning)

        requires_clarification = bool(missing) or len(fact_tables) > 1

        clarification = None
        if requires_clarification:
            parts = []
            if missing:
                parts.append(f"无法找到以下表之间的 JOIN 路径：{missing}")
            if fan_out_warning:
                parts.append(fan_out_warning)
            clarification = " ".join(parts)

        return JoinGraphResult(
            complete_tables=complete,
            paths=paths,
            pre_aggregation_required=pre_agg_required,
            missing_paths=missing,
            requires_clarification=requires_clarification,
            clarification_prompt=clarification,
        )

    def check_fan_out(self, tables: list[str]) -> list[str]:
        """检查表列表中是否存在多对多关系或多事实扇出风险。

        返回风险说明列表（空列表表示无风险）。
        """
        warnings: list[str] = []

        # 检查多事实表直接 JOIN
        fact_tables = [t for t in tables if t.startswith("fact_")]
        if len(fact_tables) > 1:
            warnings.append(
                f"多事实表 {fact_tables} 直接 JOIN 可能导致金额/数量翻倍，"
                "需要预聚合或使用 CTE 分别聚合后再关联。"
            )

        # 检查多对多关系
        for table in tables:
            for edge in self._adj.get(table, []):
                if edge.to_table in tables and edge.is_many_to_many:
                    warnings.append(
                        f"{table} → {edge.to_table} 是多对多关系，"
                        "直接 JOIN 会产生笛卡尔积，需要桥接表或预聚合。"
                    )
        return warnings

    def _build_path(
        self,
        tables: list[str],
        edges: list[GraphEdge],
    ) -> JoinPath:
        """从表列表和边列表构造 JoinPath，并标注风险。"""
        has_fan_out = any(e.is_many_to_many for e in edges)
        requires_pre_agg = any(e.requires_pre_aggregation for e in edges)

        # 找出补齐的中间表（不在原始查询表中，但属于路径的一部分）
        warning = None
        if has_fan_out:
            warning = f"路径 {' → '.join(tables)} 包含多对多关系，存在扇出风险。"
        elif requires_pre_agg:
            warning = f"路径 {' → '.join(tables)} 包含需要预聚合的关联。"

        return JoinPath(
            tables=list(tables),
            edges=list(edges),
            has_fan_out_risk=has_fan_out,
            requires_pre_aggregation=requires_pre_agg,
            warning=warning,
        )

    def has_table(self, table_name: str) -> bool:
        """判断指定表是否在图中存在。"""
        return table_name in self._nodes

    @property
    def node_count(self) -> int:
        """图中的表（节点）数量。"""
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        """图中的关系（边）总数量。"""
        return sum(len(edges) for edges in self._adj.values())


def build_graph_from_foreign_keys(
    column_metadata_list: list[Any],
) -> JoinGraph:
    """从 ColumnMetadata 的 foreign_key_ref 字段构建 Join Graph。

    foreign_key_ref 格式："{schema}.{table}.{column}"
    例如：fact_order_item.order_id → "public.fact_order.id"

    Args:
        column_metadata_list: ColumnMetadata ORM 对象列表。

    Returns:
        构建好的 JoinGraph（仅包含外键推断的关系）。
    """
    graph = JoinGraph()
    rel_id = 0  # 临时 ID，外键推断的关系没有真实 DB ID

    for col in column_metadata_list:
        if not col.foreign_key_ref:
            continue
        # foreign_key_ref 格式：schema.table.column
        parts = col.foreign_key_ref.split(".")
        if len(parts) != 3:
            continue
        _schema, ref_table, ref_col = parts
        from_table = col.table.table_name if hasattr(col, "table") else ""
        if not from_table:
            continue

        # 用临时 TableRelationship-like 对象（鸭子类型）
        fake_rel = _FakeRelationship(  # noqa: F841
            id=rel_id,
            from_table=from_table,
            to_table=ref_table,
            from_column=col.column_name,
            to_column=ref_col,
            cardinality=RelationshipCardinality.MANY_TO_ONE,
            purpose=RelationshipPurpose.JOIN,
        )
        edge = GraphEdge(
            from_table=from_table,
            to_table=ref_table,
            from_column=col.column_name,
            to_column=ref_col,
            cardinality=RelationshipCardinality.MANY_TO_ONE,
            purpose=RelationshipPurpose.JOIN,
            relationship_id=rel_id,
        )
        graph._adj.setdefault(from_table, []).append(edge)
        graph._nodes.add(from_table)
        graph._nodes.add(ref_table)
        rel_id += 1

    return graph


class _FakeRelationship:
    """测试 / 外键推断用的轻量关系对象（避免依赖完整 ORM）。"""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.is_active = True
