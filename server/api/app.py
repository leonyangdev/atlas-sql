"""FastAPI 应用入口。

应用通过工厂函数创建，测试可以注入配置和健康检查器，不需要启动真实基础设施。
"""

import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

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
        """启动 Celery worker 子进程，并在关闭时一并回收。

        worker 与 API 进程共享同一套环境变量（包括 .env.atlas 中的配置），
        不需要单独启动，也不会在测试中启动（测试通过注入 settings 绕过此分支）。
        """
        worker_proc = _start_celery_worker(runtime_settings)
        try:
            yield
        finally:
            await query_pipeline.close()
            await engine.dispose()
            if worker_proc is not None:
                worker_proc.terminate()
                worker_proc.wait(timeout=10)

    app = FastAPI(
        title="AtlasSQL API",
        version="0.1.0",
        description="Enterprise NL2SQL control and query API",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://127.0.0.1:3001",
            "http://localhost:3001",
        ],
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "x-atlas-identity", "x-admin-token"],
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
    from server.api.semantic import router as semantic_router
    from server.datasource.router import router as datasource_router
    from server.metadata.router import router as metadata_router

    app.include_router(datasource_router)
    app.include_router(metadata_router)
    app.include_router(query_router)
    app.include_router(trace_router)
    app.include_router(semantic_router)

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


def _start_celery_worker(
    settings: Settings,
) -> "subprocess.Popen[bytes] | None":  # pragma: no cover
    """在子进程中启动 Celery worker，失败时只记录警告，不阻断 API 启动。

    设计原则：
    - 测试环境（ATLAS_SKIP_WORKER=1）不启动 worker，避免在 pytest 中产生无关的子进程。
    - 明确使用 venv 目录下的 Python，而不是 sys.executable，
      防止 VS Code debugpy 在 Windows 下把 sys.executable 指向系统 Python 导致 worker
      找不到依赖、prefetch 任务后立即崩溃、任务卡在 unacked 状态。
    - Windows 不支持 fork，必须使用 --pool=solo 或 --pool=threads。
    - stdout/stderr 直接打印到同一个终端，方便本地调试。
    """
    import logging
    import os

    logger = logging.getLogger(__name__)

    if os.environ.get("ATLAS_SKIP_WORKER") == "1":
        return None

    # 找到 venv 里的 Python 可执行文件（与当前运行环境解耦）
    venv_python = _find_venv_python()
    if venv_python is None:
        logger.warning("Cannot find venv Python, skipping Celery worker startup")
        return None

    try:
        proc = subprocess.Popen(
            [
                str(venv_python),
                "-m",
                "celery",
                "-A",
                "server.tasks.celery_app:celery_app",
                "worker",
                "--loglevel=info",
                "--concurrency=2",
                "--pool=solo",  # Windows 不支持 fork，solo 模式最稳定
                "--without-heartbeat",
            ],
            env=os.environ.copy(),
        )
        logger.info("Celery worker started (pid=%d, python=%s)", proc.pid, venv_python)
        return proc
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start Celery worker: %s", exc)
        return None


def _find_venv_python() -> Path | None:  # pragma: no cover
    """找到当前项目 venv 的 Python 可执行文件路径。

    优先顺序：
    1. 环境变量 VIRTUAL_ENV（激活 venv 时由 activate 脚本设置）
    2. 当前文件向上查找 .venv 目录
    """
    import os

    # 方式 1：VIRTUAL_ENV 环境变量
    venv_dir = os.environ.get("VIRTUAL_ENV")
    if venv_dir:
        for candidate in ["Scripts/python.exe", "bin/python"]:
            p = Path(venv_dir) / candidate
            if p.exists():
                return p

    # 方式 2：从 app.py 所在目录向上查找 .venv
    here = Path(__file__).resolve()
    for parent in [here.parent, here.parent.parent, here.parent.parent.parent]:
        for candidate in [".venv/Scripts/python.exe", ".venv/bin/python"]:
            p = parent / candidate
            if p.exists():
                return p

    return None
