import httpx
import pytest

from server.api.app import create_app
from server.health import DependencyStatus
from tests.test_config import valid_settings


class FakeHealthChecker:
    def __init__(self, checks: dict[str, DependencyStatus]) -> None:
        self.checks = checks

    async def check(self) -> dict[str, DependencyStatus]:
        return self.checks


@pytest.mark.asyncio
async def test_liveness_does_not_depend_on_infrastructure() -> None:
    app = create_app(valid_settings(), FakeHealthChecker({}))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_readiness_reports_all_dependencies_up() -> None:
    checks = {
        "control_postgres": DependencyStatus(True, 1.2),
        "business_postgres": DependencyStatus(True, 1.3),
        "redis": DependencyStatus(True, 0.8),
        "opensearch": DependencyStatus(True, 5.2),
        "milvus": DependencyStatus(True, 2.1),
    }
    app = create_app(valid_settings(), FakeHealthChecker(checks))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_readiness_fails_without_affecting_liveness() -> None:
    checks = {
        "control_postgres": DependencyStatus(True, 1.2),
        "opensearch": DependencyStatus(False, 2.0, "connection_error"),
    }
    app = create_app(valid_settings(), FakeHealthChecker(checks))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        readiness = await client.get("/health/ready")
        liveness = await client.get("/health/live")

    assert readiness.status_code == 503
    assert readiness.json()["checks"]["opensearch"] == {
        "status": "down",
        "latency_ms": 2.0,
        "error_kind": "connection_error",
    }
    assert liveness.status_code == 200
