"""集中定义 AtlasSQL 运行配置及其安全输出形式。"""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从 ``ATLAS_*`` 环境变量加载并校验运行配置。

    业务库保留 reader 与 owner 两条连接：API 日常查询只能使用 reader；owner 只允许迁移和
    本地数据生成脚本使用。URL 使用 ``SecretStr``，防止日志或调试输出意外打印密码。
    """

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=(".env", ".env.atlas"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    environment: str = "development"
    log_level: str = "INFO"
    control_database_url: SecretStr
    business_database_url: SecretStr
    business_owner_database_url: SecretStr | None = None
    redis_url: SecretStr
    opensearch_url: SecretStr
    milvus_host: str = "127.0.0.1"
    milvus_port: int = Field(default=19530, ge=1, le=65535)
    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    query_data_version: str = "v0.1.0"
    query_schema_version: str = "001"
    query_timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    query_statement_timeout_ms: int = Field(default=10_000, ge=100, le=60_000)
    query_max_concurrency: int = Field(default=8, ge=1, le=100)
    query_max_rows: int = Field(default=500, ge=1, le=10_000)
    llm_provider: Literal["fake", "deepseek"] = "fake"
    llm_api_base: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_max_output_tokens: int = Field(default=2_048, ge=128, le=8_192)
    llm_max_retries: int = Field(default=1, ge=0, le=2)
    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "ATLAS_DEEPSEEK_API_KEY"),
    )

    @field_validator("control_database_url", "business_database_url", "business_owner_database_url")
    @classmethod
    def validate_postgres_url(cls, value: SecretStr | None) -> SecretStr | None:
        """提前拒绝错误驱动，避免在首次连接时才得到难定位的异常。"""

        if value is None:
            return None
        scheme = urlsplit(value.get_secret_value()).scheme
        if scheme not in {"postgresql", "postgresql+asyncpg"}:
            raise ValueError("must use a postgresql or postgresql+asyncpg URL")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        """Redis 同时允许本地明文协议和生产 TLS 协议。"""

        if urlsplit(value.get_secret_value()).scheme not in {"redis", "rediss"}:
            raise ValueError("must use a redis or rediss URL")
        return value

    @field_validator("opensearch_url")
    @classmethod
    def validate_opensearch_url(cls, value: SecretStr) -> SecretStr:
        """OpenSearch 通过 HTTP API 检查，只接受 HTTP(S) URL。"""

        if urlsplit(value.get_secret_value()).scheme not in {"http", "https"}:
            raise ValueError("must use an http or https URL")
        return value

    @field_validator("deepseek_api_key", mode="before")
    @classmethod
    def blank_deepseek_key_is_not_configured(cls, value: object) -> object:
        """把示例环境中的空值规范为 None，避免安全摘要误报已配置。"""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def databases_must_be_isolated(self) -> "Settings":
        """阻止控制库连接串被直接复用为业务查询连接串。"""

        if (
            self.control_database_url.get_secret_value()
            == self.business_database_url.get_secret_value()
        ):
            raise ValueError("control and business databases must use different URLs")
        return self

    @model_validator(mode="after")
    def selected_llm_provider_must_be_configured(self) -> "Settings":
        """真实 Provider 必须在启动阶段发现缺失密钥，而不是处理请求时才失败。"""

        if self.llm_provider == "deepseek" and (
            self.deepseek_api_key is None or not self.deepseek_api_key.get_secret_value().strip()
        ):
            raise ValueError("DEEPSEEK_API_KEY is required when llm_provider=deepseek")
        return self

    def safe_summary(self) -> dict[str, str | int | float]:
        """返回可安全写入日志的配置摘要，所有连接 URL 都用固定占位符代替。"""
        return {
            "environment": self.environment,
            "log_level": self.log_level,
            "control_database_url": "**********",
            "business_database_url": "**********",
            "business_owner_database_url": (
                "**********" if self.business_owner_database_url is not None else "not_configured"
            ),
            "redis_url": "**********",
            "opensearch_url": "**********",
            "milvus_host": self.milvus_host,
            "milvus_port": self.milvus_port,
            "dependency_timeout_seconds": self.dependency_timeout_seconds,
            "query_data_version": self.query_data_version,
            "query_schema_version": self.query_schema_version,
            "query_timeout_ms": self.query_timeout_ms,
            "query_statement_timeout_ms": self.query_statement_timeout_ms,
            "query_max_concurrency": self.query_max_concurrency,
            "query_max_rows": self.query_max_rows,
            "llm_provider": self.llm_provider,
            "llm_api_base": self.llm_api_base,
            "llm_model": self.llm_model,
            "llm_max_output_tokens": self.llm_max_output_tokens,
            "llm_max_retries": self.llm_max_retries,
            "deepseek_api_key": (
                "**********" if self.deepseek_api_key is not None else "not_configured"
            ),
        }


@lru_cache
def get_settings() -> Settings:
    """进程内只解析一次环境配置；测试可直接构造 ``Settings``，不依赖此缓存。"""

    return Settings()  # type: ignore[call-arg]
