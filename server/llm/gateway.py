"""文本生成模型网关及 DeepSeek Chat Completions API 适配器。

业务模块只依赖 ``LLMGateway`` 协议。Provider 的认证头、HTTP 状态码和响应结构都封装在
适配器内，既避免 SDK 类型向上泄漏，也让离线测试可以使用确定性的 Fake。
"""

from __future__ import annotations

import asyncio
import enum
import json
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from langsmith import traceable


class LLMErrorKind(enum.StrEnum):
    """Provider 层稳定失败分类。"""

    CONFIGURATION = "configuration"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    PROVIDER = "provider"
    INVALID_RESPONSE = "invalid_response"


class LLMGatewayError(RuntimeError):
    """不携带响应正文或密钥的 Provider 异常。"""

    def __init__(self, kind: LLMErrorKind, *, retryable: bool) -> None:
        super().__init__(kind.value)
        self.kind = kind
        self.retryable = retryable


@dataclass(frozen=True)
class LLMRequest:
    """一次结构化文本生成请求。"""

    prompt: str
    system_prompt: str
    prompt_hash: str
    response_schema: dict[str, object]
    max_output_tokens: int
    timeout_ms: int


@dataclass(frozen=True)
class LLMResponse:
    """Provider 无关的生成结果和可观测字段。"""

    output_text: str
    model_version: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    provider_request_id: str | None = None
    latency_ms: float = 0.0


class LLMGateway(Protocol):
    """SQL 生成只需依赖的最小模型端口。"""

    @property
    def model_version(self) -> str: ...

    @property
    def model_parameters(self) -> dict[str, str | int | float | bool]: ...

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class DeepSeekChatGateway:
    """DeepSeek Chat Completions API 的 JSON Output 适配器。

    ``client`` 注入点只用于测试或共享连接；未注入时每次调用创建短生命周期客户端，避免
    应用关闭时遗留连接。API Key 仅存在于 Authorization header，从不进入异常或返回对象。
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str = "https://api.deepseek.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise LLMGatewayError(LLMErrorKind.CONFIGURATION, retryable=False)
        self._api_key = api_key
        self._model = model
        self._api_base = api_base.rstrip("/")
        self._client = client

    @property
    def model_version(self) -> str:
        return f"deepseek:{self._model}"

    @property
    def model_parameters(self) -> dict[str, str | int | float | bool]:
        return {
            "provider": "deepseek",
            "model": self._model,
            "structured_output": True,
            "thinking": False,
        }

    @traceable(run_type="llm", name="deepseek-complete")
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """调用 Chat Completions，并把 HTTP/结构异常收敛为类型化失败。"""

        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.prompt},
            ],
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        started = time.perf_counter()
        try:
            if self._client is not None:
                response = await self._client.post(
                    f"{self._api_base}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=request.timeout_ms / 1_000,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self._api_base}/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=request.timeout_ms / 1_000,
                    )
        except httpx.TimeoutException as exc:
            raise LLMGatewayError(LLMErrorKind.TIMEOUT, retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMGatewayError(LLMErrorKind.PROVIDER, retryable=True) from exc

        if response.status_code == 429:
            raise LLMGatewayError(LLMErrorKind.RATE_LIMIT, retryable=True)
        if response.status_code >= 500:
            raise LLMGatewayError(LLMErrorKind.PROVIDER, retryable=True)
        if response.status_code >= 400:
            raise LLMGatewayError(LLMErrorKind.PROVIDER, retryable=False)

        try:
            body = response.json()
            output_text = _extract_chat_content(body)
            usage = body.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens))
            response_id = body.get("id")
            response_model = str(body.get("model") or self._model)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMGatewayError(LLMErrorKind.INVALID_RESPONSE, retryable=False) from exc

        if output_text is None:
            # DeepSeek 官方文档说明 JSON Output 偶尔可能返回空 content，允许流水线有限重试。
            raise LLMGatewayError(LLMErrorKind.INVALID_RESPONSE, retryable=True)
        return LLMResponse(
            output_text=output_text,
            model_version=f"deepseek:{response_model}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            provider_request_id=str(response_id) if response_id is not None else None,
            latency_ms=round((time.perf_counter() - started) * 1_000, 2),
        )


def _extract_chat_content(body: object) -> str | None:
    """从非流式 Chat Completions 响应中读取首个 assistant content。"""

    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") == "length":
        return None
    message = choice.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) and content else None


DEFAULT_FAKE_OUTPUT = json.dumps(
    {
        "action": "generate",
        "sql": (
            "SELECT COUNT(DISTINCT id) AS paid_order_count FROM fact_order "
            "WHERE order_status IN ('PAID', 'COMPLETED') AND is_test = false"
        ),
        "reason": None,
    },
    ensure_ascii=False,
    separators=(",", ":"),
)


@dataclass
class FakeLLMGateway:
    """可重放、可延迟、可注入失败的离线模型网关。"""

    output_text: str = DEFAULT_FAKE_OUTPUT
    delay_seconds: float = 0.0
    failures: list[LLMGatewayError] = field(default_factory=list)
    calls: list[LLMRequest] = field(default_factory=list)

    @property
    def model_version(self) -> str:
        return "fake:sql-v1"

    @property
    def model_parameters(self) -> dict[str, str | int | float | bool]:
        return {
            "provider": "fake",
            "model": "sql-v1",
            "structured_output": True,
            "store": False,
        }

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)
        if self.failures:
            raise self.failures.pop(0)
        # Fake token 数只用于测试记录链路，不代表任何真实 Provider 的计费方式。
        input_tokens = max(1, (len(request.system_prompt.encode("utf-8")) + len(request.prompt.encode("utf-8"))) // 4)
        output_tokens = max(1, len(self.output_text.encode("utf-8")) // 4)
        return LLMResponse(
            output_text=self.output_text,
            model_version=self.model_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            provider_request_id=f"fake-{request.prompt_hash[:12]}",
        )
