"""V3 语义层 ORM 模型。

包含：
- MetricDefinition        指标定义及版本快照
- MetricVersion           不可变版本快照（已发布后只读）
- SemanticDimension       维度定义
- BusinessGlossary        术语/同义词
- FiscalCalendar          财年日历
- MetricActiveVersion     每个指标的当前发布版本指针（支持原子切换）
- VerifiedQuery           已验证的问题-SQL 样例

设计约束：
1. 指标主键为稳定的业务 ID（slug 格式，例如 "net_sales"），不以展示名为主键。
2. 已发布的 MetricVersion 不允许原地修改；需要变更时必须创建新版本（V3-S02 状态机负责）。
3. MetricActiveVersion 是对当前生效版本的指针，支持原子切换与回滚。
4. VerifiedQuery 记录审核人和时间，不自动继承新版本的可信状态。
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.db import Base


# ──────────────────────────────────────────────────────────────
# 枚举
# ──────────────────────────────────────────────────────────────


class SemanticStatus(enum.StrEnum):
    """指标/语义对象的生命周期状态。

    状态转移：
        DRAFT → TESTING → PUBLISHED → DEPRECATED
        TESTING → DRAFT  （回退修改）
        PUBLISHED → DEPRECATED （停用）

    约束：已 PUBLISHED 的版本禁止原地修改，必须创建新草稿。
    """

    DRAFT = "draft"
    TESTING = "testing"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class MetricGrain(enum.StrEnum):
    """指标聚合粒度，决定该指标允许的分析维度。"""

    ORDER_ITEM = "order_item"         # 订单明细粒度
    ORDER = "order"                   # 订单粒度
    CUSTOMER = "customer"             # 客户粒度
    PERIOD = "period"                 # 时间段聚合
    SNAPSHOT_DATE = "snapshot_date"   # 日末快照粒度（禁止跨日求和）
    WAREHOUSE_SKU = "warehouse_sku"   # 仓库 SKU 粒度


class TimeRole(enum.StrEnum):
    """指标依赖的事件时间字段语义。"""

    PAID_AT = "paid_at"             # 按支付时间归属
    REFUNDED_AT = "refunded_at"     # 按退款时间归属
    CREATED_AT = "created_at"       # 按创建时间归属
    EVENT_AT = "event_at"           # 按通用事件时间归属
    SNAPSHOT_DATE = "snapshot_date" # 按快照日期归属


class ZeroDenominatorPolicy(enum.StrEnum):
    """除法类指标分母为零时的处理策略。"""

    NULL_WITH_REASON = "null_with_reason"   # 返回 NULL 并附说明
    ZERO = "zero"                           # 返回 0
    NOT_APPLICABLE = "not_applicable"       # 非除法指标，不适用


class DimensionType(enum.StrEnum):
    """维度类型：时间维度、分类维度、层级维度等。"""

    TIME = "time"
    CATEGORICAL = "categorical"
    HIERARCHICAL = "hierarchical"
    GEOGRAPHY = "geography"
    CUSTOMER_SEGMENT = "customer_segment"


class GlossaryStatus(enum.StrEnum):
    """术语状态。"""

    ACTIVE = "active"
    DEPRECATED = "deprecated"


class VerifiedQueryStatus(enum.StrEnum):
    """可信查询样例状态。

    - DRAFT: 待审核，不可被召回
    - VERIFIED: 已审核通过，可被 few-shot 召回
    - INVALID: 已失效（指标/schema 变动后未重验）
    """

    DRAFT = "draft"
    VERIFIED = "verified"
    INVALID = "invalid"


# ──────────────────────────────────────────────────────────────
# 指标定义（MetricDefinition）
# ──────────────────────────────────────────────────────────────


class MetricDefinition(Base):
    """指标定义主表。

    每个指标有一个稳定的 ``metric_id``（slug 格式，例如 "net_sales"），
    不以展示名（label）作主键，避免同名口径冲突时主键冲突。

    当前草稿内容保存在此表；发布后通过 MetricVersion 创建不可变快照。
    MetricActiveVersion 指向当前生效的版本号。
    """

    __tablename__ = "metric_definition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 稳定业务 ID，e.g. "net_sales"、"gross_margin_rate"
    metric_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # 展示名，e.g. "销售额"（可中英文，允许重名，但 metric_id 唯一）
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    # 业务域，e.g. "sales"、"finance"
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 聚合粒度
    grain: Mapped[MetricGrain] = mapped_column(
        Enum(MetricGrain, name="metric_grain"), nullable=False
    )
    # SQL 聚合表达式，例如 "SUM(fact_order_item.net_amount) - SUM(refunded_item_amount)"
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    # 强制过滤条件列表（JSON 字符串数组），必须全部注入 SQL
    required_filters: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 该指标依赖的物理字段列表（JSON 字符串数组），格式 "table.column"
    dependent_columns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 允许分析的维度列表（JSON 字符串数组），空列表表示无限制
    allowed_dimensions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 事件时间角色
    time_role: Mapped[TimeRole] = mapped_column(
        Enum(TimeRole, name="time_role"), nullable=False, server_default="paid_at"
    )
    # 分母为零处理策略
    zero_denominator_policy: Mapped[ZeroDenominatorPolicy] = mapped_column(
        Enum(ZeroDenominatorPolicy, name="zero_denominator_policy"),
        nullable=False,
        server_default="not_applicable",
    )
    # 单位，e.g. "CNY"、"件"
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 币种，e.g. "CNY"
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # 同义词列表（JSON 字符串数组），供意图链接使用
    synonyms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 是否是敏感指标（受限字段，需要特定权限）
    is_sensitive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 关于时间口径的说明文字
    time_rule_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 警告信息（e.g. "禁止对明细行毛利率做简单平均"）
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 当前生命周期状态（草稿/测试/发布/废弃）
    status: Mapped[SemanticStatus] = mapped_column(
        Enum(SemanticStatus, name="semantic_status"),
        nullable=False,
        server_default="draft",
    )
    # 最近一次审核人
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # 反向关系
    versions: Mapped[list["MetricVersion"]] = relationship(
        "MetricVersion", back_populates="metric", cascade="all, delete-orphan"
    )
    active_version: Mapped[Optional["MetricActiveVersion"]] = relationship(
        "MetricActiveVersion", back_populates="metric", uselist=False
    )


class MetricVersion(Base):
    """指标版本快照（不可变）。

    每次指标进入 PUBLISHED 状态时，当前草稿内容会被固化为一个 MetricVersion。
    此后无论草稿如何修改，该快照不变，保证历史查询记录可以找到当时的口径。

    约束：version_number 在同一 metric_id 下单调递增，由服务层保证。
    """

    __tablename__ = "metric_version"
    __table_args__ = (
        UniqueConstraint("metric_id", "version_number", name="uq_metric_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("metric_definition.metric_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # 快照时刻的完整定义（JSON），结构与 MetricDefinition 字段对应
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    # 本次发布的变更说明
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 发布时关联的回归测试结果 ID（V3-S02 填入）
    regression_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    metric: Mapped["MetricDefinition"] = relationship(
        "MetricDefinition", back_populates="versions"
    )


class MetricActiveVersion(Base):
    """每个指标当前生效的版本指针。

    独立出来支持原子切换（UPDATE WHERE）和回滚（改回旧版本号）。
    发布操作：UPDATE metric_active_version SET version_number=N WHERE metric_id=X
    """

    __tablename__ = "metric_active_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("metric_definition.metric_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    metric: Mapped["MetricDefinition"] = relationship(
        "MetricDefinition", back_populates="active_version"
    )


# ──────────────────────────────────────────────────────────────
# 语义维度（SemanticDimension）
# ──────────────────────────────────────────────────────────────


class SemanticDimension(Base):
    """语义维度定义。

    维度是指标分析的切分轴，例如「城市」「品类」「渠道」。
    维度对应一个或多个物理列（通过 column_ref_list 关联）。
    """

    __tablename__ = "semantic_dimension"
    __table_args__ = (
        UniqueConstraint("dimension_id", name="uq_dimension_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dimension_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dimension_type: Mapped[DimensionType] = mapped_column(
        Enum(DimensionType, name="dimension_type"), nullable=False
    )
    # 对应的物理列列表（JSON 字符串数组），格式 "table.column"
    column_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 同义词列表，用于意图链接
    synonyms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 层级路径（仅 HIERARCHICAL 维度），e.g. ["region", "city", "store"]
    hierarchy_levels: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SemanticStatus] = mapped_column(
        Enum(SemanticStatus, name="semantic_status"),
        nullable=False,
        server_default="draft",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ──────────────────────────────────────────────────────────────
# 业务术语（BusinessGlossary）
# ──────────────────────────────────────────────────────────────


class BusinessGlossary(Base):
    """业务术语与同义词词典。

    存储业务语言中的自然词汇到系统对象（指标/维度/实体）的映射。
    Value Linking 的别名字典（V2 中硬编码为 _ALIAS_DICT）在 V3 迁移到此表。
    """

    __tablename__ = "business_glossary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 术语原文，例如"销售收入"、"营收"、"华东"
    term: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    # 规范化的目标对象 ID（指标/维度/实体），格式 "metric:net_sales" 或 "dimension:region"
    canonical_target_id: Mapped[str] = mapped_column(String(256), nullable=False)
    # 目标类型，e.g. "metric"、"dimension"、"value"
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 如果是值映射，记录实际数据库值，e.g. "华东" → "East China"
    mapped_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 所属域
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 负责人（数据分析师/业务方）
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 权威定义来源
    authoritative_source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[GlossaryStatus] = mapped_column(
        Enum(GlossaryStatus, name="glossary_status"),
        nullable=False,
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ──────────────────────────────────────────────────────────────
# 财年日历（FiscalCalendar）
# ──────────────────────────────────────────────────────────────


class FiscalCalendar(Base):
    """财年日历定义。

    支持不与自然年对齐的财年（例如 2/1～1/31）。
    V3-S03 时间冲突检测（财年 vs 自然年）时查询此表。
    """

    __tablename__ = "fiscal_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 财年标识，e.g. "FY2026"
    fiscal_year: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # 该财年在哪个数据源/域下适用
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 财年开始日期（格式 "MM-DD"，例如 "02-01" 表示 2 月 1 日）
    start_month_day: Mapped[str] = mapped_column(String(5), nullable=False)
    # 财年结束日期（格式 "MM-DD"）
    end_month_day: Mapped[str] = mapped_column(String(5), nullable=False)
    # 描述（e.g. "零售集团采用 2 月开始的财年"）
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ──────────────────────────────────────────────────────────────
# 可信查询样例（VerifiedQuery）
# ──────────────────────────────────────────────────────────────


class VerifiedQuery(Base):
    """已验证的问题-SQL 样例（Verified Query Repository）。

    用于动态 few-shot：根据当前问题通过 embedding + BM25 检索最相关的样例，
    注入 SQL 生成上下文。

    约束：
    - 仅 VERIFIED 状态的样例才能被召回。
    - 语义或 Schema 变动后，关联样例状态自动降为 INVALID，需重新审核。
    - 不自动继承新版本的可信状态。
    """

    __tablename__ = "verified_query"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 稳定 slug（例如 UUID），用于引用和 embedding 文档 ID
    query_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 使用的语义模型版本（发布时的指标版本快照标识，格式 "net_sales:v3,gross_margin_rate:v2"）
    semantic_version_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 使用的 schema 版本（查询时的 query_schema_version）
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 标签列表（JSON 字符串数组），例如 ["同比", "华东", "销售额"]
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 样例描述/说明
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 依赖的指标 ID 列表（JSON），变动时触发重验
    dependent_metric_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[VerifiedQueryStatus] = mapped_column(
        Enum(VerifiedQueryStatus, name="verified_query_status"),
        nullable=False,
        server_default="draft",
        index=True,
    )
    # 是否属于锁定测试集（锁定集样例不能被 few-shot 召回，防止题库泄漏）
    is_test_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verified_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 最近一次校验执行结果（语法 + 只读结果）
    last_validation_result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 失效原因（当 status=INVALID 时填写）
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ──────────────────────────────────────────────────────────────
# 语义索引记录（SemanticIndexRecord）
# ──────────────────────────────────────────────────────────────


class SemanticIndexRecord(Base):
    """语义对象的向量/词法索引版本记录。

    每次发布指标/术语/维度后，触发异步索引构建任务，
    此表记录每个对象在 Milvus / OpenSearch 中的索引状态和版本。
    """

    __tablename__ = "semantic_index_record"
    __table_args__ = (
        Index("ix_semantic_index_object", "object_type", "object_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 对象类型，e.g. "metric"、"dimension"、"glossary"、"verified_query"
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 对象 ID（metric_id / dimension_id / query_id 等）
    object_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # 索引版本（等于对应 MetricVersion.version_number 或构建时间戳）
    index_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # 是否已完成索引构建
    is_indexed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
