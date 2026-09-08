import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.health import DependencyChecker
from tests.test_config import valid_settings


@pytest.mark.asyncio
async def test_dependency_checker_reports_every_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = DependencyChecker(valid_settings())
    postgres = AsyncMock()
    monkeypatch.setattr(checker, "_postgres", postgres)
    monkeypatch.setattr(checker, "_redis", AsyncMock())
    monkeypatch.setattr(checker, "_opensearch", AsyncMock())
    monkeypatch.setattr(checker, "_milvus", AsyncMock())

    result = await checker.check()

    assert set(result) == {
        "control_postgres",
        "business_postgres",
        "redis",
        "opensearch",
        "milvus",
    }
    assert all(status.ok for status in result.values())
    assert postgres.await_count == 2


@pytest.mark.asyncio
async def test_dependency_checker_classifies_timeout_and_connection_error() -> None:
    checker = DependencyChecker(valid_settings(dependency_timeout_seconds=0.001))

    async def slow_check() -> None:
        await asyncio.sleep(0.1)

    async def connection_failure() -> None:
        raise ConnectionRefusedError

    timeout = await checker._measure(slow_check)
    connection = await checker._measure(connection_failure)

    assert not timeout.ok and timeout.error_kind == "timeout"
    assert not connection.ok and connection.error_kind == "connection_error"


@pytest.mark.asyncio
async def test_postgres_health_query_closes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = AsyncMock()
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr("server.health.asyncpg.connect", connect)
    checker = DependencyChecker(valid_settings())

    await checker._postgres("postgresql://user:password@localhost/database")

    connection.fetchval.assert_awaited_once_with("SELECT 1")
    connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_health_ping_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    monkeypatch.setattr("server.health.redis.from_url", lambda _: client)
    checker = DependencyChecker(valid_settings())

    await checker._redis()

    client.ping.assert_awaited_once()
    client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_milvus_health_check_closes_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    writer = MagicMock()
    writer.wait_closed = AsyncMock()
    open_connection = AsyncMock(return_value=(object(), writer))
    monkeypatch.setattr("server.health.asyncio.open_connection", open_connection)
    checker = DependencyChecker(valid_settings())

    await checker._milvus()

    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()
