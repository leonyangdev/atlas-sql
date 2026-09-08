from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from ATLAS_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=(".env", ".env.atlas"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    log_level: str = "INFO"
    control_database_url: SecretStr
    business_database_url: SecretStr
    redis_url: SecretStr
    opensearch_url: SecretStr
    milvus_host: str = "127.0.0.1"
    milvus_port: int = Field(default=19530, ge=1, le=65535)
    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    @field_validator("control_database_url", "business_database_url")
    @classmethod
    def validate_postgres_url(cls, value: SecretStr) -> SecretStr:
        scheme = urlsplit(value.get_secret_value()).scheme
        if scheme not in {"postgresql", "postgresql+asyncpg"}:
            raise ValueError("must use a postgresql or postgresql+asyncpg URL")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        if urlsplit(value.get_secret_value()).scheme not in {"redis", "rediss"}:
            raise ValueError("must use a redis or rediss URL")
        return value

    @field_validator("opensearch_url")
    @classmethod
    def validate_opensearch_url(cls, value: SecretStr) -> SecretStr:
        if urlsplit(value.get_secret_value()).scheme not in {"http", "https"}:
            raise ValueError("must use an http or https URL")
        return value

    @model_validator(mode="after")
    def databases_must_be_isolated(self) -> "Settings":
        if (
            self.control_database_url.get_secret_value()
            == self.business_database_url.get_secret_value()
        ):
            raise ValueError("control and business databases must use different URLs")
        return self

    def safe_summary(self) -> dict[str, str | int | float]:
        """Return values safe to include in logs and diagnostics."""
        return {
            "environment": self.environment,
            "log_level": self.log_level,
            "control_database_url": "**********",
            "business_database_url": "**********",
            "redis_url": "**********",
            "opensearch_url": "**********",
            "milvus_host": self.milvus_host,
            "milvus_port": self.milvus_port,
            "dependency_timeout_seconds": self.dependency_timeout_seconds,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
