"""V1-S02 模型网关、Prompt 和结构化 SQL 生成测试。"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from pydantic import ValidationError

from server.domain.query import QueryErrorCode, QueryRequest, QueryStatus
from server.generation.prompt import PROMPT_VERSION, SQLPromptBuilder
from server.generation.sql import (
    MAX_MODEL_OUTPUT_CHARS,
    MAX_SQL_CHARS,
    BaselineSQLGenerationPipeline,
    SQLPayloadError,
    parse_sql_payload,
)
from server.llm.gateway import (
    DeepSeekChatGateway,
    FakeLLMGateway,
    LLMErrorKind,
    LLMGatewayError,
    LLMRequest,
)
from server.orchestrator.query import QueryContext, QueryOrchestrator
from server.query.repository import InMemoryQueryRepository
from tests.test_config import valid_settings


def make_context(timeout_ms: int = 5_000) -> QueryContext:
    return QueryContext(
        trace_id=uuid.uuid4(),
        identity="public",
        data_version="v0.1.0",
        schema_version="001",
        model_version="fake:sql-v1",
        timeout_ms=timeout_ms,
        metric_ids=("net_sales",),
    )


def make_llm_request() -> LLMRequest:
    return LLMRequest(
        prompt='{"instruction":"output json"}',
        system_prompt="You are a SQL generator.",
        prompt_hash="a" * 64,
        response_schema={"type": "object"},
        max_output_tokens=512,
        timeout_ms=5_000,
    )


@pytest.mark.asyncio
async def test_fake_gateway_replays_same_request() -> None:
    gateway = FakeLLMGateway()
    request = make_llm_request()

    first = await gateway.complete(request)
    second = await gateway.complete(request)

    assert first == second
    assert first.total_tokens == first.input_tokens + first.output_tokens
    assert len(gateway.calls) == 2


@pytest.mark.asyncio
async def test_deepseek_gateway_uses_json_output_and_records_usage() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"action":"generate","sql":"SELECT 1","reason":null}',
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        gateway = DeepSeekChatGateway(
            api_key="test-secret",
            model="deepseek-v4-flash",
            client=client,
        )
        response = await gateway.complete(make_llm_request())

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["authorization"] == "Bearer test-secret"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert response.output_text.startswith("{")
    assert response.total_tokens == 15
    assert response.provider_request_id == "chatcmpl-test"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_kind", "retryable"),
    [
        (429, LLMErrorKind.RATE_LIMIT, True),
        (503, LLMErrorKind.PROVIDER, True),
        (401, LLMErrorKind.PROVIDER, False),
    ],
)
async def test_deepseek_gateway_maps_http_errors(
    status_code: int,
    expected_kind: LLMErrorKind,
    retryable: bool,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code))
    ) as client:
        gateway = DeepSeekChatGateway(api_key="test-secret", model="test-model", client=client)
        with pytest.raises(LLMGatewayError) as error:
            await gateway.complete(make_llm_request())

    assert error.value.kind == expected_kind
    assert error.value.retryable is retryable
    assert "test-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_deepseek_gateway_maps_transport_timeout() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("contains-sensitive-upstream-detail", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        gateway = DeepSeekChatGateway(api_key="test-secret", model="test-model", client=client)
        with pytest.raises(LLMGatewayError) as error:
            await gateway.complete(make_llm_request())

    assert error.value.kind == LLMErrorKind.TIMEOUT
    assert "sensitive" not in str(error.value)


def test_prompt_is_deterministic_and_contains_only_allowed_schema() -> None:
    builder = SQLPromptBuilder()
    first = builder.build(
        question="今年净销售额是多少？",
        metric_ids=("net_sales",),
        data_version="v0.1.0",
        schema_version="001",
        model_parameters={"provider": "fake", "model": "sql-v1"},
    )
    second = builder.build(
        question="今年净销售额是多少？",
        metric_ids=("net_sales",),
        data_version="v0.1.0",
        schema_version="001",
        model_parameters={"provider": "fake", "model": "sql-v1"},
    )
    parsed = json.loads(first.user_prompt)

    assert first == second
    assert first.version == PROMPT_VERSION
    assert len(first.prompt_hash) == 64
    assert parsed["dialect"] == "postgresql"
    assert len(parsed["allowed_schema"]) >= 1  # 按关键词动态裁剪后至少有 1 张表
    assert parsed["metric_drafts"][0]["id"] == "net_sales"
    assert "order_no" not in first.user_prompt
    assert "tenant_id" not in first.user_prompt
    assert "test.yaml" not in first.user_prompt
    assert "tune.yaml" not in first.user_prompt


def test_prompt_hash_changes_with_question_or_model_parameters() -> None:
    builder = SQLPromptBuilder()
    first = builder.build(
        question="今年销售额",
        metric_ids=("net_sales",),
        data_version="v0.1.0",
        schema_version="001",
        model_parameters={"model": "a"},
    )
    changed = builder.build(
        question="去年销售额",
        metric_ids=("net_sales",),
        data_version="v0.1.0",
        schema_version="001",
        model_parameters={"model": "b"},
    )

    assert first.prompt_hash != changed.prompt_hash


def test_parse_sql_payload_accepts_structured_sql() -> None:
    payload = parse_sql_payload('{"action":"generate","sql":"  SELECT 1  ","reason":null}')

    assert payload.action == "generate"
    assert payload.sql == "SELECT 1"


@pytest.mark.parametrize(
    ("output", "code"),
    [
        ("not-json", QueryErrorCode.LLM_INVALID_OUTPUT),
        ('{"action":"generate","sql":null,"reason":null}', QueryErrorCode.LLM_NO_SQL),
        (
            '{"action":"clarify","sql":"SELECT 1","reason":"ambiguous"}',
            QueryErrorCode.LLM_INVALID_OUTPUT,
        ),
        ("x" * (MAX_MODEL_OUTPUT_CHARS + 1), QueryErrorCode.LLM_INVALID_OUTPUT),
        (
            json.dumps({"action": "generate", "sql": "S" * (MAX_SQL_CHARS + 1), "reason": None}),
            QueryErrorCode.LLM_INVALID_OUTPUT,
        ),
    ],
)
def test_parse_sql_payload_rejects_invalid_output(output: str, code: QueryErrorCode) -> None:
    with pytest.raises(SQLPayloadError) as error:
        parse_sql_payload(output)

    assert error.value.code == code


@pytest.mark.asyncio
async def test_pipeline_records_prompt_model_and_tokens() -> None:
    gateway = FakeLLMGateway()
    pipeline = BaselineSQLGenerationPipeline(gateway)

    result = await pipeline.run(QueryRequest(question="今年净销售额"), make_context())

    assert result.status == QueryStatus.PROCESSING
    assert result.sql is not None
    assert result.prompt_version == PROMPT_VERSION
    assert result.prompt_hash == gateway.calls[0].prompt_hash
    assert result.model_version == "fake:sql-v1"
    assert result.input_tokens > 0
    assert result.total_tokens == result.input_tokens + result.output_tokens


@pytest.mark.asyncio
async def test_pipeline_retries_rate_limit_then_succeeds() -> None:
    gateway = FakeLLMGateway(failures=[LLMGatewayError(LLMErrorKind.RATE_LIMIT, retryable=True)])
    pipeline = BaselineSQLGenerationPipeline(gateway, max_retries=1)

    result = await pipeline.run(QueryRequest(question="订单量"), make_context())

    assert result.status == QueryStatus.PROCESSING
    assert len(gateway.calls) == 2


@pytest.mark.asyncio
async def test_pipeline_returns_typed_rate_limit_after_retry_budget() -> None:
    gateway = FakeLLMGateway(
        failures=[
            LLMGatewayError(LLMErrorKind.RATE_LIMIT, retryable=True),
            LLMGatewayError(LLMErrorKind.RATE_LIMIT, retryable=True),
        ]
    )
    pipeline = BaselineSQLGenerationPipeline(gateway, max_retries=1)

    result = await pipeline.run(QueryRequest(question="订单量"), make_context())

    assert result.status == QueryStatus.FAILED
    assert result.error_code == QueryErrorCode.LLM_RATE_LIMITED
    assert len(gateway.calls) == 2


@pytest.mark.asyncio
async def test_pipeline_limits_invalid_output_retries() -> None:
    gateway = FakeLLMGateway(output_text="not-json")
    pipeline = BaselineSQLGenerationPipeline(gateway, max_retries=1)

    result = await pipeline.run(QueryRequest(question="订单量"), make_context())

    assert result.status == QueryStatus.FAILED
    assert result.error_code == QueryErrorCode.LLM_INVALID_OUTPUT
    assert len(gateway.calls) == 2


@pytest.mark.asyncio
async def test_pipeline_enforces_total_timeout_budget() -> None:
    gateway = FakeLLMGateway(delay_seconds=0.05)
    pipeline = BaselineSQLGenerationPipeline(gateway, max_retries=0)

    result = await pipeline.run(QueryRequest(question="订单量"), make_context(timeout_ms=10))

    assert result.status == QueryStatus.FAILED
    assert result.error_code == QueryErrorCode.LLM_TIMEOUT


@pytest.mark.asyncio
async def test_orchestrator_persists_generation_metadata() -> None:
    repository = InMemoryQueryRepository()
    pipeline = BaselineSQLGenerationPipeline(FakeLLMGateway())
    orchestrator = QueryOrchestrator(
        repository,
        data_version="v0.1.0",
        schema_version="001",
        model_version=pipeline.model_version,
        timeout_ms=5_000,
        pipeline=pipeline,
    )

    response = await orchestrator.submit(QueryRequest(question="订单量"), "public")
    state = repository.records[response.trace_id]

    assert response.status == QueryStatus.PROCESSING
    assert response.sql is not None
    assert response.trace.prompt_hash == state.prompt_hash
    assert response.trace.total_tokens == state.total_tokens


def test_deepseek_configuration_requires_key_and_redacts_it() -> None:
    with pytest.raises(ValidationError, match="DEEPSEEK_API_KEY"):
        valid_settings(llm_provider="deepseek", deepseek_api_key="")

    settings = valid_settings(llm_provider="deepseek", deepseek_api_key="real-secret")
    assert settings.safe_summary()["deepseek_api_key"] == "**********"
    assert "real-secret" not in repr(settings)
