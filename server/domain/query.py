"""问数请求、响应与 Trace 的稳定领域契约。

V1 先固定 API 与编排器之间的数据形状。后续模型生成、SQL 校验和执行模块只能填充这些
契约，不能把 Provider SDK 或数据库驱动对象泄漏到 API 层。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

MAX_QUESTION_LENGTH = 2_000


class QueryStatus(enum.StrEnum):
    """一次问数请求对用户可见的状态。"""

    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    CLARIFICATION_REQUIRED = "clarification_required"
    REJECTED = "rejected"
    FAILED = "failed"


class QueryErrorCode(enum.StrEnum):
    """稳定错误码；用户提示可以演进，调用方只依赖错误码。"""

    OUT_OF_SCOPE = "out_of_scope"
    AMBIGUOUS_METRIC = "ambiguous_metric"
    LLM_TIMEOUT = "llm_timeout"
    LLM_RATE_LIMITED = "llm_rate_limited"
    LLM_INVALID_OUTPUT = "llm_invalid_output"
    LLM_NO_SQL = "llm_no_sql"
    LLM_PROVIDER_ERROR = "llm_provider_error"
    SQL_PARSE_ERROR = "sql_parse_error"
    SQL_SECURITY_VIOLATION = "sql_security_violation"
    SQL_OUT_OF_SCOPE = "sql_out_of_scope"
    EXECUTION_TIMEOUT = "execution_timeout"
    EXECUTION_BUSY = "execution_busy"
    EXECUTION_ERROR = "execution_error"
    INTERNAL_ERROR = "internal_error"


class QueryRequest(BaseModel):
    """用户提交的最小问数请求。

    ``session_id`` 由前端长期持有，用于未来多轮上下文；``trace_id`` 通常由服务端生成，
    但允许网关传入 UUID，从而贯通一次分布式请求。
    """

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    trace_id: uuid.UUID | None = None

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        """去除首尾空白，并拒绝看起来非空、实际只有空白的输入。"""

        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str) -> str:
        """会话标识是日志维度，禁止只包含空白。"""

        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id must not be blank")
        return normalized


class QueryColumn(BaseModel):
    """结果列及其数据库类型。"""

    name: str
    data_type: str


class QueryError(BaseModel):
    """可安全展示的类型化错误，不承载底层异常原文。"""

    code: QueryErrorCode
    message: str


class QueryStageTrace(BaseModel):
    """单个处理阶段的摘要；V1 后续故事逐步填充耗时。"""

    name: str
    status: str
    duration_ms: float | None = None


class QueryTrace(BaseModel):
    """复现一次请求所需的版本、身份与预算信息。"""

    trace_id: uuid.UUID
    identity: str
    status: QueryStatus
    data_version: str
    schema_version: str
    model_version: str
    timeout_ms: int
    prompt_version: str | None = None
    prompt_hash: str | None = None
    model_parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    execution_ms: float | None = None
    referenced_tables: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)
    metric_ids: list[str] = Field(default_factory=list)
    stages: list[QueryStageTrace] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


QueryCell = str | int | float | bool | None


class MetricDefinitionBrief(BaseModel):
    """查询结果中附带的指标定义简要信息（供前端展示口径说明）。"""

    metric_id: str
    label: str
    expression: str
    required_filters: list[str] = Field(default_factory=list)
    time_role: str = "paid_at"
    warning: str | None = None
    time_rule_note: str | None = None


class QueryResponse(BaseModel):
    """所有问数状态共用的响应体。

    未执行完成时 ``sql``、``columns`` 和 ``rows`` 保持空值，而不是伪造演示结果。结果行
    采用与列顺序一致的二维数组，避免重复携带列名。
    ``metric_definitions`` 由 V3 Pipeline 填入，展示本次查询实际使用的指标口径。
    """

    question: str
    session_id: str
    trace_id: uuid.UUID
    status: QueryStatus
    sql: str | None = None
    columns: list[QueryColumn] = Field(default_factory=list)
    rows: list[list[QueryCell]] = Field(default_factory=list)
    error: QueryError | None = None
    truncated: bool = False
    execution_ms: float | None = None
    summary: str | None = None
    referenced_tables: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)
    metric_definitions: list[MetricDefinitionBrief] = Field(default_factory=list)
    trace: QueryTrace
