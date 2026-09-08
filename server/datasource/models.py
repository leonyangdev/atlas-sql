"""数据源控制面 ORM 模型。

数据源（DataSource）是 AtlasSQL 管理的被分析数据库的登记条目。
凭据不在控制库明文存储，而是以引用字符串（如环境变量名或 Vault 路径）保存。

后续元数据采集、索引构建和权限控制都以数据源为根，因此这里是控制面最核心的实体。
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.db import Base


class DataSourceKind(enum.StrEnum):
    """支持的数据源类型；V0 只需要 PostgreSQL，预留枚举便于后续扩展。"""

    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    BIGQUERY = "bigquery"
    SNOWFLAKE = "snowflake"


class DataSourceStatus(enum.StrEnum):
    """数据源生命周期状态。"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class SyncStatus(enum.StrEnum):
    """单次同步任务的执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DataSource(Base):
    """已登记的数据源。

    ``credential_ref`` 不存明文连接串，只允许 ``env:VAR_NAME`` 或 ``vault:path/to/secret``
    两种形式的安全引用，实际凭据在应用层解析，控制库日志不会出现密码。

    每个数据源有一个稳定的 ``slug`` 用于 URL 路径，修改 slug 时需要同时更新依赖引用。
    """

    __tablename__ = "datasource"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[DataSourceKind] = mapped_column(
        Enum(DataSourceKind, name="datasource_kind"), nullable=False
    )
    host: Mapped[str] = mapped_column(String(256), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 连接凭据只以引用字符串存储，例如 "env:ATLAS_BUSINESS_OWNER_DATABASE_URL"
    credential_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[DataSourceStatus] = mapped_column(
        Enum(DataSourceStatus, name="datasource_status"),
        nullable=False,
        insert_default=DataSourceStatus.ACTIVE,
        server_default="ACTIVE",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # 反向关系：一个数据源对应多个元数据表、同步日志
    tables: Mapped[list["TableMetadata"]] = relationship(
        "TableMetadata", back_populates="datasource", cascade="all, delete-orphan"
    )
    sync_jobs: Mapped[list["MetadataSyncJob"]] = relationship(
        "MetadataSyncJob", back_populates="datasource", cascade="all, delete-orphan"
    )


class TableMetadata(Base):
    """已采集的表级元数据。

    ``is_deleted`` 用于标记已在源库消失的表，而不是物理删除，保留人工注释。
    ``manual_*`` 字段由管理员手工补充；增量同步时这些字段保持不变。
    """

    __tablename__ = "table_metadata"
    __table_args__ = (
        UniqueConstraint("datasource_id", "schema_name", "table_name", name="uq_table_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datasource_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("datasource.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    table_type: Mapped[str] = mapped_column(String(32), nullable=False)  # TABLE / VIEW
    row_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 从数据库注释采集的原始描述
    raw_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 管理员手工补充的业务属性（增量同步不覆盖）
    manual_business_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    manual_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manual_grain: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_authoritative_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manual_aliases: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组
    is_deleted: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    # 记录是哪次同步采集到这条元数据
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 控制库内部时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    datasource: Mapped["DataSource"] = relationship("DataSource", back_populates="tables")
    columns: Mapped[list["ColumnMetadata"]] = relationship(
        "ColumnMetadata", back_populates="table", cascade="all, delete-orphan"
    )


class ColumnMetadata(Base):
    """已采集的列级元数据。

    ``sample_values`` 存储经过脱敏处理的少量样例值（JSON 字符串数组），供检索阶段
    Value Linking 使用。敏感列的样例值可在人工审核后设为空字符串。
    """

    __tablename__ = "column_metadata"
    __table_args__ = (UniqueConstraint("table_id", "column_name", name="uq_column_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("table_metadata.id", ondelete="CASCADE"), nullable=False, index=True
    )
    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    character_maximum_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    numeric_precision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    numeric_scale: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_nullable: Mapped[bool] = mapped_column(nullable=False)
    column_default: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary_key: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    foreign_key_ref: Mapped[str | None] = mapped_column(
        String(256), nullable=True
    )  # "schema.table.column"
    raw_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 管理员手工补充
    manual_business_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    manual_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_sensitivity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manual_aliases: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组
    # 脱敏后的样例值（JSON 字符串数组，最多 10 个）
    sample_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    table: Mapped["TableMetadata"] = relationship("TableMetadata", back_populates="columns")


class MetadataSyncJob(Base):
    """元数据同步任务执行记录。

    ``idempotency_key`` 由调用方生成（通常是 Celery task_id），用于防止同一任务重复提交。
    ``schema_version`` 记录本次同步时控制面 schema 版本，便于诊断迁移后的兼容性问题。
    """

    __tablename__ = "metadata_sync_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datasource_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("datasource.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Celery task_id 或其他调用方的幂等标识
    idempotency_key: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status"), nullable=False, insert_default=SyncStatus.PENDING
    )
    # 重试计数；达到上限时不再重试并标记为 FAILED
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, insert_default=0)
    # 记录本次采集的对象数量
    tables_discovered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    columns_discovered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 可公开的错误摘要（不含连接串或密码）
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    datasource: Mapped["DataSource"] = relationship("DataSource", back_populates="sync_jobs")
