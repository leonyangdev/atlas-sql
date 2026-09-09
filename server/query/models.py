"""问数请求在控制库中的持久化模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from server.db import Base
from server.domain.query import QueryStatus


class QueryRecord(Base):
    """请求生命周期记录。

    保存请求、身份、版本、预算和状态。生成阶段补充候选 SQL、Prompt 指纹和 token 用量，
    后续执行阶段复用同一记录更新结果，保证 trace_id 始终可以还原完整链路。
    """

    __tablename__ = "query_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    identity: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QueryStatus] = mapped_column(
        Enum(QueryStatus, name="query_status"), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    columns: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)
    rows: Mapped[list[list[str | int | float | bool | None]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    truncated: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    metric_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model_parameters: Mapped[dict[str, str | int | float | bool]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    execution_ms: Mapped[float | None] = mapped_column(nullable=True)
    referenced_tables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    referenced_columns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    stages: Mapped[list[dict[str, str | float | None]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
