"""组装 SQL 生成流水线（V1 和 V3）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.config import Settings
from server.execution.postgres import AsyncpgReadOnlyExecutor
from server.generation.sql import BaselineSQLGenerationPipeline
from server.generation.v3_pipeline import V3SQLGenerationPipeline
from server.llm.factory import create_llm_gateway
from server.orchestrator.pipeline import SafeQueryPipeline
from server.validation.sql import SQLValidator

if TYPE_CHECKING:
    from server.semantic.registry import SemanticRegistry


def create_sql_generation_pipeline(settings: Settings) -> SafeQueryPipeline:
    """在组合根强制组装 V1 生成、校验和只读执行三个阶段。"""

    generator = BaselineSQLGenerationPipeline(
        create_llm_gateway(settings),
        max_output_tokens=settings.llm_max_output_tokens,
        max_retries=settings.llm_max_retries,
    )
    executor = AsyncpgReadOnlyExecutor(
        settings.business_database_url.get_secret_value(),
        statement_timeout_ms=settings.query_statement_timeout_ms,
        max_concurrency=settings.query_max_concurrency,
        max_rows=settings.query_max_rows,
    )
    return SafeQueryPipeline(generator, SQLValidator(), executor)


def create_v3_pipeline(
    settings: Settings,
    registry: "SemanticRegistry",
) -> SafeQueryPipeline:
    """在组合根组装 V3 语义上下文 SQL 生成流水线。

    使用 V3SQLGenerationPipeline（含 SemanticRegistry + SQLPromptBuilderV3）
    替换 V1 的 BaselineSQLGenerationPipeline，校验和执行层保持不变。
    SQLValidator 使用 strict_scope=False，允许跨域表（dim_customer、fact_inventory_snapshot 等）。

    Args:
        settings: 运行配置。
        registry: 已从 YAML 加载的 SemanticRegistry（含 V3 全部指标定义）。
    """
    generator = V3SQLGenerationPipeline(
        create_llm_gateway(settings),
        registry=registry,
        max_output_tokens=settings.llm_max_output_tokens,
        max_retries=settings.llm_max_retries,
    )
    executor = AsyncpgReadOnlyExecutor(
        settings.business_database_url.get_secret_value(),
        statement_timeout_ms=settings.query_statement_timeout_ms,
        max_concurrency=settings.query_max_concurrency,
        max_rows=settings.query_max_rows,
    )
    # strict_scope=False：允许跨域表，只做语法和只读安全校验
    return SafeQueryPipeline(generator, SQLValidator(strict_scope=False), executor)
