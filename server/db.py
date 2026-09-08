"""控制库的 SQLAlchemy 基础设施。

这里不创建业务库引擎。业务查询身份与控制面身份必须保持分离，避免应用误写被分析数据。
"""

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有控制面 ORM 模型的声明基类，供 Alembic 收集 metadata。"""


def sqlalchemy_url(url: SecretStr) -> str:
    """把通用 PostgreSQL URL 转为 SQLAlchemy asyncpg URL。

    已显式指定异步驱动时保持原值，使配置可以在本地和部署环境共用。
    """

    value = url.get_secret_value()
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


def create_control_engine(url: SecretStr) -> AsyncEngine:
    """创建带失效连接探测的控制库异步引擎。"""

    return create_async_engine(sqlalchemy_url(url), pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """创建异步 session 工厂；expire_on_commit=False 避免懒加载在 async 场景下触发。"""

    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
