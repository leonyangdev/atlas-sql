"""索引发布状态管理。

控制库记录每批索引的状态（BUILDING / PUBLISHED / FAILED），防止新旧快照混用。
每次索引构建完成后必须通过 ``publish_index_batch`` 把状态更新为 PUBLISHED，
检索层只读 PUBLISHED 批次的版本标记，未发布的批次不可见。

这套机制保证：
1. 索引构建失败时不会更新 published_version，检索仍使用上一批。
2. 维度变更后不能直接写旧 collection，需要先创建新 collection 再切换。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from server.db import Base


class IndexBatchStatus(enum.StrEnum):
    """索引批次的生命周期状态。"""

    PENDING = "pending"
    BUILDING = "building"
    PUBLISHED = "published"
    FAILED = "failed"


class IndexBatch(Base):
    """索引构建批次记录。

    每次触发索引构建时创建一条记录，完成后更新为 PUBLISHED 或 FAILED。
    ``index_type`` 区分 schema / metrics / verified_queries 等不同索引类型。
    ``object_count`` 是构建完成后核对用的文档数，与 OpenSearch/Milvus 中的实际数量比对。
    ``embedding_model_version`` 和 ``dimension`` 记录构建时使用的模型版本；
    模型升级后，旧批次的 collection 不能直接写入新向量。
    """

    __tablename__ = "index_batch"
    __table_args__ = (UniqueConstraint("index_type", "batch_key", name="uq_index_batch_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 区分不同索引类型：schema / metrics / verified_queries
    index_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # 幂等键，通常是触发任务的 Celery task_id
    batch_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[IndexBatchStatus] = mapped_column(
        Enum(IndexBatchStatus, name="index_batch_status"),
        nullable=False,
        insert_default=IndexBatchStatus.PENDING,
    )
    # 构建完成时的文档总数（OpenSearch + Milvus 各自核对用）
    object_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 使用的 Embedding 模型版本标识
    embedding_model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 向量维度；维度变更时拒绝直接写旧 collection
    dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 控制库 schema 版本，用于检测 stale 索引
    metadata_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 可公开的错误摘要（不含连接串）
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PublishedIndexVersion(Base):
    """当前已发布的索引版本指针。

    每种 index_type 只保留一行，记录最新的已发布批次 ID 和模型版本。
    检索层读取此表决定使用哪个 collection / index，不直接读 IndexBatch 状态。
    """

    __tablename__ = "published_index_version"
    __table_args__ = (UniqueConstraint("index_type", name="uq_published_index_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # 指向 IndexBatch.id
    index_batch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    object_count: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
