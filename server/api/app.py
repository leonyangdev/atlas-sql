from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from server.config import Settings, get_settings
from server.health import DependencyChecker, HealthChecker


def create_app(
    settings: Settings | None = None,
    health_checker: HealthChecker | None = None,
) -> FastAPI:
    app = FastAPI(
        title="AtlasSQL API",
        version="0.1.0",
        description="Enterprise NL2SQL control and query API",
    )
    runtime_settings = settings or get_settings()
    app.state.settings = runtime_settings
    app.state.health_checker = health_checker or DependencyChecker(runtime_settings)

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", tags=["health"])
    async def readiness(request: Request) -> JSONResponse:
        checks = await request.app.state.health_checker.check()
        ready = all(check.ok for check in checks.values())
        body = {
            "status": "ready" if ready else "not_ready",
            "checks": {
                name: {
                    "status": "up" if check.ok else "down",
                    "latency_ms": check.latency_ms,
                    **({"error_kind": check.error_kind} if check.error_kind else {}),
                }
                for name, check in checks.items()
            },
        }
        return JSONResponse(
            body,
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return app
