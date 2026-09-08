"""Alembic 控制库迁移环境。

此文件只读取 ``Base.metadata`` 和控制库 URL。NovaRetail 业务表使用 datasets 下的独立迁移器，
从入口上阻止两类 schema 被错误地迁入同一个数据库。
"""

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 导入所有 ORM 模型，使 Alembic 能通过 Base.metadata 感知全部表定义
import server.datasource.models  # noqa: F401
import server.search.index_status  # noqa: F401
from server.config import get_settings
from server.db import Base, sqlalchemy_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """不连接数据库生成 SQL，适合审查即将执行的控制库变更。"""

    context.configure(
        url=sqlalchemy_url(get_settings().control_database_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在 Alembic 提供的同步连接上执行 metadata 差异。"""

    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """创建短生命周期异步引擎，迁移结束后主动释放连接池。"""

    configuration: dict[str, Any] = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = sqlalchemy_url(get_settings().control_database_url)
    connectable = async_engine_from_config(configuration, prefix="sqlalchemy.")
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


# Alembic CLI 根据是否传入 --sql 选择离线或在线路径。
if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
