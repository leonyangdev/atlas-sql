"""Celery 应用工厂。

Celery 应用在模块级别创建，worker 启动时自动发现 server/tasks/ 下的全部任务模块。
broker 和 backend 都使用 Redis，与健康检查中的 Redis 实例共享。

任务序列化使用 JSON（不使用 pickle），避免反序列化安全风险。
"""

import logging

from celery import Celery

from server.config import get_settings

logger = logging.getLogger(__name__)


def create_celery_app() -> Celery:
    """创建并配置 Celery 应用实例。

    配置项说明：
    - task_serializer/result_serializer = json：明文序列化，便于调试和安全审计。
    - task_acks_late = True：任务在执行完成后才确认，防止 worker 崩溃时任务丢失。
    - task_reject_on_worker_lost = True：与 acks_late 配合，崩溃的任务会重新入队。
    - task_max_retries / default_retry_delay：统一的重试策略。
    """
    settings = get_settings()
    redis_url = settings.redis_url.get_secret_value()

    app = Celery(
        "atlas_sql",
        broker=redis_url,
        backend=redis_url,
        include=[
            "server.tasks.metadata_sync",
            "server.tasks.index_build",
        ],
    )

    app.conf.update(
        # 序列化格式
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # 可靠性
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        # 默认重试策略
        task_max_retries=3,
        task_default_retry_delay=60,  # 秒
        # 结果保存 24 小时，便于管理界面查询
        result_expires=86400,
        # 时区
        timezone="UTC",
        enable_utc=True,
    )

    return app


# 模块级单例；worker 和 API 进程通过 from server.tasks.celery_app import celery_app 导入
celery_app = create_celery_app()
