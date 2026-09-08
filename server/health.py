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
    ok: bool
    latency_ms: float
    error_kind: str | None = None


class HealthChecker(Protocol):
    async def check(self) -> dict[str, DependencyStatus]: ...


class DependencyChecker:
    """Checks infrastructure without leaking connection strings or exception messages."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def check(self) -> dict[str, DependencyStatus]:
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
        return round((time.perf_counter() - started) * 1000, 2)

    async def _postgres(self, dsn: str) -> None:
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        connection = await asyncpg.connect(
            dsn=dsn, timeout=self.settings.dependency_timeout_seconds
        )
        try:
            await connection.fetchval("SELECT 1")
        finally:
            await connection.close()

    async def _redis(self) -> None:
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
        async with httpx.AsyncClient(
            timeout=self.settings.dependency_timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.get(self.settings.opensearch_url.get_secret_value())
            response.raise_for_status()

    async def _milvus(self) -> None:
        reader, writer = await asyncio.open_connection(
            self.settings.milvus_host,
            self.settings.milvus_port,
        )
        writer.close()
        await writer.wait_closed()
