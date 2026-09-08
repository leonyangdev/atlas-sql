from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for control-plane SQLAlchemy models."""


def sqlalchemy_url(url: SecretStr) -> str:
    value = url.get_secret_value()
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


def create_control_engine(url: SecretStr) -> AsyncEngine:
    return create_async_engine(sqlalchemy_url(url), pool_pre_ping=True)
