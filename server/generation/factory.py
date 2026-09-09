"""组装 V1 SQL 生成流水线。"""

from server.config import Settings
from server.execution.postgres import AsyncpgReadOnlyExecutor
from server.generation.sql import BaselineSQLGenerationPipeline
from server.llm.factory import create_llm_gateway
from server.orchestrator.pipeline import SafeQueryPipeline
from server.validation.sql import SQLValidator


def create_sql_generation_pipeline(settings: Settings) -> SafeQueryPipeline:
    """在组合根强制组装生成、校验和只读执行三个阶段。"""

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
