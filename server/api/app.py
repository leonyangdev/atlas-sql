"""FastAPI 应用入口。

应用通过工厂函数创建，测试可以注入配置和健康检查器，不需要启动真实基础设施。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.config import Settings, get_settings
from server.db import create_control_engine, create_session_factory
from server.generation.factory import create_sql_generation_pipeline
from server.health import DependencyChecker, HealthChecker
from server.orchestrator.query import QueryOrchestrator


def create_app(
    settings: Settings | None = None,
    health_checker: HealthChecker | None = None,
    query_orchestrator: QueryOrchestrator | None = None,
) -> FastAPI:
    """组装 API 与进程级依赖。

    ``settings`` 和 ``health_checker`` 的可选注入点用于测试和未来多环境启动。运行时对象放入
    ``app.state``，让路由通过请求所属应用读取，避免使用难以替换的模块级全局变量。

    控制库引擎和 session 工厂也挂载到 app.state，供数据源等路由读取。
    """

    runtime_settings = settings or get_settings()
    query_pipeline = create_sql_generation_pipeline(runtime_settings)
    engine = create_control_engine(runtime_settings.control_database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """统一释放控制库和业务库连接池。"""

        yield
        await query_pipeline.close()
        await engine.dispose()

    app = FastAPI(
        title="AtlasSQL API",
        version="0.1.0",
        description="Enterprise NL2SQL control and query API",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "x-atlas-identity"],
    )
    app.state.settings = runtime_settings
    app.state.health_checker = health_checker or DependencyChecker(runtime_settings)
    app.state.query_orchestrator = query_orchestrator
    app.state.query_pipeline = query_pipeline

    # 控制库 ORM 引擎与 session 工厂
    app.state.db_engine = engine
    app.state.db_session_factory = create_session_factory(engine)

    # 注册路由
    from server.api.query import router as query_router
    from server.api.trace import router as trace_router
    from server.datasource.router import router as datasource_router
    from server.metadata.router import router as metadata_router

    app.include_router(datasource_router)
    app.include_router(metadata_router)
    app.include_router(query_router)
    app.include_router(trace_router)

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        """只证明 API 进程仍能处理事件循环，不访问任何外部依赖。"""

        return {"status": "alive"}

    @app.get("/health/ready", tags=["health"])
    async def readiness(request: Request) -> JSONResponse:
        """检查承接真实请求所需的全部依赖，任一失败即返回 HTTP 503。"""

        checks = await request.app.state.health_checker.check()
        ready = all(check.ok for check in checks.values())
        # 对外只返回依赖类别和错误分类。底层异常可能包含主机、用户名甚至连接串，不能透传。
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
