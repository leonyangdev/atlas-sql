"""结构化 SQL 输出解析和基线生成流水线。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from server.domain.query import QueryErrorCode, QueryRequest, QueryStatus
from server.generation.prompt import SQLPromptBuilder
from server.llm.gateway import LLMErrorKind, LLMGateway, LLMGatewayError, LLMRequest, LLMResponse
from server.orchestrator.query import QueryContext, QueryOutcome

MAX_MODEL_OUTPUT_CHARS = 20_000
MAX_SQL_CHARS = 10_000


class SQLGenerationPayload(BaseModel):
    """模型 JSON 输出经本地强校验后的形状。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["generate", "clarify", "reject"]
    sql: str | None
    reason: str | None


class SQLPayloadError(ValueError):
    """携带用户安全错误码的解析异常。"""

    def __init__(self, code: QueryErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def parse_sql_payload(output_text: str) -> SQLGenerationPayload:
    """限制长度并验证 JSON 结构、action 与 SQL 的组合关系。"""

    if len(output_text) > MAX_MODEL_OUTPUT_CHARS:
        raise SQLPayloadError(QueryErrorCode.LLM_INVALID_OUTPUT)
    try:
        raw = json.loads(output_text)
        payload = SQLGenerationPayload.model_validate(raw)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise SQLPayloadError(QueryErrorCode.LLM_INVALID_OUTPUT) from exc

    if payload.action == "generate":
        if payload.sql is None or not payload.sql.strip():
            raise SQLPayloadError(QueryErrorCode.LLM_NO_SQL)
        if len(payload.sql) > MAX_SQL_CHARS:
            raise SQLPayloadError(QueryErrorCode.LLM_INVALID_OUTPUT)
        return payload.model_copy(update={"sql": payload.sql.strip()})

    if payload.sql is not None:
        raise SQLPayloadError(QueryErrorCode.LLM_INVALID_OUTPUT)
    if payload.reason is None or not payload.reason.strip():
        raise SQLPayloadError(QueryErrorCode.LLM_INVALID_OUTPUT)
    return payload


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    provider_request_id: str | None = None
    model_version: str | None = None

    def add(self, response: LLMResponse) -> None:
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.total_tokens += response.total_tokens
        self.provider_request_id = response.provider_request_id
        self.model_version = response.model_version


class BaselineSQLGenerationPipeline:
    """构建 Prompt、调用模型、有限重试并解析候选 SQL。"""

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        prompt_builder: SQLPromptBuilder | None = None,
        max_output_tokens: int = 2_048,
        max_retries: int = 1,
    ) -> None:
        self._gateway = gateway
        self._prompt_builder = prompt_builder or SQLPromptBuilder()
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries

    @property
    def model_version(self) -> str:
        return self._gateway.model_version

    async def run(self, request: QueryRequest, context: QueryContext) -> QueryOutcome:
        package = self._prompt_builder.build(
            question=request.question,
            metric_ids=context.metric_ids,
            data_version=context.data_version,
            schema_version=context.schema_version,
            model_parameters=self._gateway.model_parameters,
        )
        llm_request = package.to_llm_request(
            max_output_tokens=self._max_output_tokens,
            timeout_ms=context.timeout_ms,
        )
        usage = _Usage()
        try:
            async with asyncio.timeout(context.timeout_ms / 1_000):
                return await self._attempt_generation(llm_request, package.version, usage)
        except TimeoutError:
            return self._failure(
                QueryErrorCode.LLM_TIMEOUT,
                "模型调用超时，请稍后重试。",
                package.version,
                package.prompt_hash,
                usage,
            )

    async def _attempt_generation(
        self,
        request: LLMRequest,
        prompt_version: str,
        usage: _Usage,
    ) -> QueryOutcome:
        last_code = QueryErrorCode.LLM_PROVIDER_ERROR
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._gateway.complete(request)
                usage.add(response)
                payload = parse_sql_payload(response.output_text)
            except LLMGatewayError as exc:
                last_code = _gateway_error_code(exc.kind)
                if exc.retryable and attempt < self._max_retries:
                    continue
                return self._failure(
                    last_code,
                    _safe_error_message(last_code),
                    prompt_version,
                    request.prompt_hash,
                    usage,
                )
            except SQLPayloadError as exc:
                last_code = exc.code
                if attempt < self._max_retries:
                    continue
                return self._failure(
                    last_code,
                    _safe_error_message(last_code),
                    prompt_version,
                    request.prompt_hash,
                    usage,
                )
            return self._success(payload, prompt_version, request.prompt_hash, usage)

        return self._failure(
            last_code,
            _safe_error_message(last_code),
            prompt_version,
            request.prompt_hash,
            usage,
        )

    def _success(
        self,
        payload: SQLGenerationPayload,
        prompt_version: str,
        prompt_hash: str,
        usage: _Usage,
    ) -> QueryOutcome:
        if payload.action == "generate":
            # SQL 仍需经过 V1-S03 AST 校验和只读执行，因此状态保持 processing。
            return QueryOutcome(
                status=QueryStatus.PROCESSING,
                sql=payload.sql,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                model_version=usage.model_version or self.model_version,
                model_parameters=self._gateway.model_parameters,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                provider_request_id=usage.provider_request_id,
            )
        if payload.action == "clarify":
            return QueryOutcome(
                status=QueryStatus.CLARIFICATION_REQUIRED,
                error_code=QueryErrorCode.AMBIGUOUS_METRIC,
                error_message="问题存在歧义，请补充指标口径或查询范围。",
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                model_version=usage.model_version or self.model_version,
                model_parameters=self._gateway.model_parameters,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                provider_request_id=usage.provider_request_id,
            )
        return QueryOutcome(
            status=QueryStatus.REJECTED,
            error_code=QueryErrorCode.OUT_OF_SCOPE,
            error_message="该问题不在 V1 固定 Sales 查询范围内。",
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            model_version=usage.model_version or self.model_version,
            model_parameters=self._gateway.model_parameters,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            provider_request_id=usage.provider_request_id,
        )

    def _failure(
        self,
        code: QueryErrorCode,
        message: str,
        prompt_version: str,
        prompt_hash: str,
        usage: _Usage,
    ) -> QueryOutcome:
        return QueryOutcome(
            status=QueryStatus.FAILED,
            error_code=code,
            error_message=message,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            model_version=usage.model_version or self.model_version,
            model_parameters=self._gateway.model_parameters,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            provider_request_id=usage.provider_request_id,
        )


def _gateway_error_code(kind: LLMErrorKind) -> QueryErrorCode:
    return {
        LLMErrorKind.TIMEOUT: QueryErrorCode.LLM_TIMEOUT,
        LLMErrorKind.RATE_LIMIT: QueryErrorCode.LLM_RATE_LIMITED,
        LLMErrorKind.INVALID_RESPONSE: QueryErrorCode.LLM_INVALID_OUTPUT,
        LLMErrorKind.CONFIGURATION: QueryErrorCode.LLM_PROVIDER_ERROR,
        LLMErrorKind.PROVIDER: QueryErrorCode.LLM_PROVIDER_ERROR,
    }[kind]


def _safe_error_message(code: QueryErrorCode) -> str:
    return {
        QueryErrorCode.LLM_TIMEOUT: "模型调用超时，请稍后重试。",
        QueryErrorCode.LLM_RATE_LIMITED: "模型服务繁忙，请稍后重试。",
        QueryErrorCode.LLM_INVALID_OUTPUT: "模型返回格式无效，请重试。",
        QueryErrorCode.LLM_NO_SQL: "模型未返回可用 SQL，请补充问题后重试。",
        QueryErrorCode.LLM_PROVIDER_ERROR: "模型服务暂时不可用，请稍后重试。",
    }[code]
