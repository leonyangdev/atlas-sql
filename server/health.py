"""基础设施健康检查及安全的错误分类。"""

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import asyncpg
import httpx
import redis.asyncio as redis

from server.config import Settings


@dataclass(frozen=True)
class DependencyStatus:
    """单项依赖结果；只保存状态、耗时和可公开的错误类别。"""

    ok: bool
    latency_ms: float
    error_kind: str | None = None


class HealthChecker(Protocol):
    """readiness 路由依赖的最小协议，测试可以用内存实现替代真实检查。"""

    async def check(self) -> dict[str, DependencyStatus]: ...


class DependencyChecker:
    """并发检查全部基础设施，同时避免泄露连接串和原始异常。"""

    def __init__(self, settings: Settings) -> None:
        """保存已通过 Pydantic 校验的配置，不在构造阶段发起网络请求。"""

        self.settings = settings

    async def check(self) -> dict[str, DependencyStatus]:
        """并发执行五项检查，使 readiness 延迟接近最慢单项而非全部耗时之和。"""

        checks: dict[str, Callable[[], Awaitable[None]]] = {
            "control_postgres": lambda: self._postgres(
                self.settings.control_database_url.get_secret_value()
            ),
            "business_postgres": lambda: self._postgres(
                self.settings.business_database_url.get_secret_value()
            ),
            "redis": self._redis,
            "opensearch": self._opensearch,
            "milvus": self._milvus,
        }
        results = await asyncio.gather(*(self._measure(check) for check in checks.values()))
        return dict(zip(checks, results, strict=True))

    async def _measure(self, check: Callable[[], Awaitable[None]]) -> DependencyStatus:
        """统一应用超时、计时和错误分类，适配器只负责最小连通性动作。"""

        started = time.perf_counter()
        try:
            async with asyncio.timeout(self.settings.dependency_timeout_seconds):
                await check()
        except TimeoutError:
            return DependencyStatus(False, self._elapsed(started), "timeout")
        except (ConnectionError, OSError):
            return DependencyStatus(False, self._elapsed(started), "connection_error")
        except (asyncpg.InvalidAuthorizationSpecificationError, redis.AuthenticationError):
            return DependencyStatus(False, self._elapsed(started), "authentication_error")
        except (asyncpg.PostgresError, redis.RedisError, httpx.HTTPError):
            return DependencyStatus(False, self._elapsed(started), "dependency_error")
        return DependencyStatus(True, self._elapsed(started))

    @staticmethod
    def _elapsed(started: float) -> float:
        """把单调时钟间隔换算为便于诊断的毫秒值。"""

        return round((time.perf_counter() - started) * 1000, 2)

    async def _postgres(self, dsn: str) -> None:
        """执行最小查询并始终关闭临时连接。"""

        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        connection = await asyncpg.connect(
            dsn=dsn, timeout=self.settings.dependency_timeout_seconds
        )
        try:
            await connection.fetchval("SELECT 1")
        finally:
            await connection.close()

    async def _redis(self) -> None:
        """发送 PING；兼容 Redis 客户端同步或异步返回形式。"""

        client = redis.from_url(self.settings.redis_url.get_secret_value())
        try:
            ping_result = client.ping()
            if inspect.isawaitable(ping_result):
                await ping_result
        finally:
            close_result = client.aclose()
            if inspect.isawaitable(close_result):
                await close_result

    async def _opensearch(self) -> None:
        """访问集群根端点，并忽略宿主机代理以保证本地地址可直连。"""

        async with httpx.AsyncClient(
            timeout=self.settings.dependency_timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.get(self.settings.opensearch_url.get_secret_value())
            response.raise_for_status()

    async def _milvus(self) -> None:
        """用 TCP 握手验证 Milvus 端口可达，不在健康检查阶段创建 SDK 客户端。"""

        reader, writer = await asyncio.open_connection(
            self.settings.milvus_host,
            self.settings.milvus_port,
        )
        writer.close()
        await writer.wait_closed()
