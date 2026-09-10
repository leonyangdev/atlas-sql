"""V3 语义上下文 SQL 生成流水线。

与 V1 BaselineSQLGenerationPipeline 的区别：
1. run() 先用 SemanticRegistry 把 metric_ids 解析为完整 MetricEntry 定义
2. 用 SemanticContextBuilder 组装 SemanticContext（含指标表达式、强制过滤、警告）
3. 用 SQLPromptBuilderV3 替换静态 YAML Prompt 构建
4. SQL 生成后仍经过 SafeQueryPipeline（SQLValidator + 只读执行）

与 V1 完全兼容：QueryRequest / QueryContext / QueryOutcome 契约不变，
SafeQueryPipeline 仍作为外层包装，V3Pipeline 只替换了生成器部分。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from server.domain.query import QueryErrorCode, QueryRequest, QueryStatus
from server.generation.context import SemanticContext, SemanticContextBuilder
from server.generation.prompt import SQLPromptBuilderV3
from server.generation.sql import (
    SQLPayloadError,
    _Usage,
    parse_sql_payload,
)
from server.llm.gateway import LLMGatewayError, LLMRequest
from server.orchestrator.query import QueryContext, QueryOutcome
from server.search.retrieval import SchemaContext

if TYPE_CHECKING:
    from server.llm.gateway import LLMGateway
    from server.semantic.registry import SemanticRegistry

logger = logging.getLogger(__name__)

# V3 semantic_version_ref 标识（来自 v3 YAML catalog_version）
_V3_SEMANTIC_VERSION = "v3.0.0-yaml"


class V3SQLGenerationPipeline:
    """V3 语义上下文 SQL 生成器。

    在 run() 中：
    1. 从 SemanticRegistry 解析 metric_ids → MetricEntry 列表
    2. 构建 SemanticContext（含表达式、required_filters、warning）
    3. 用 SQLPromptBuilderV3 构建 Prompt
    4. 调用 LLM 生成 SQL

    Args:
        gateway: LLM 网关（与 V1 完全相同）。
        registry: 已加载的 SemanticRegistry（含 V3 全部指标）。
        context_builder: SemanticContextBuilder 实例，默认宽容域（不过滤敏感指标）。
        max_output_tokens: 模型最大输出 token 数。
        max_retries: 失败重试次数。
    """

    def __init__(
        self,
        gateway: "LLMGateway",
        registry: "SemanticRegistry",
        context_builder: SemanticContextBuilder | None = None,
        max_output_tokens: int = 2_048,
        max_retries: int = 1,
    ) -> None:
        self._gateway = gateway
        self._registry = registry
        self._context_builder = context_builder or SemanticContextBuilder(
            token_budget=6_000,
            max_examples=5,
            # 不传 allowed_domains，允许全域（Finance/Sales/Customer/Inventory 都可以）
            allowed_domains=None,
        )
        self._prompt_builder = SQLPromptBuilderV3()
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries

    @property
    def model_version(self) -> str:
        return self._gateway.model_version

    async def run(self, request: QueryRequest, context: QueryContext) -> QueryOutcome:
        """执行 V3 生成流程。"""
        # 1. 解析 metric_ids → MetricEntry 列表
        metric_entries = self._resolve_metric_entries(context.metric_ids, request.question)

        # 2. 构建 SemanticContext
        # 当前阶段（V3）没有 V2 检索层，使用 V1 静态 Schema 白名单作为表结构来源；
        # 同时把指标 dependent_columns / expression 里的表也加入 allowed_schema。
        # V4 将把 SchemaContext 替换为 TwoLevelRetriever 的真实召回结果。
        schema_context = self._build_v1_schema_context(request.question, metric_entries)

        semantic_ctx = self._context_builder.build(
            schema_context=schema_context,
            metric_entries=metric_entries,
            semantic_version_ref=_V3_SEMANTIC_VERSION,
        )

        # 3. 构建 Prompt
        package = self._prompt_builder.build(
            question=request.question,
            semantic_context=semantic_ctx,
            data_version=context.data_version,
            schema_version=context.schema_version,
            model_parameters=self._gateway.model_parameters,
        )
        llm_request = package.to_llm_request(
            max_output_tokens=self._max_output_tokens,
            timeout_ms=context.timeout_ms,
        )

        usage = _Usage()
        try:
            async with asyncio.timeout(context.timeout_ms / 1_000):
                return await self._attempt_generation(
                    llm_request, package.version, package.prompt_hash, usage, semantic_ctx
                )
        except TimeoutError:
            return self._failure(
                QueryErrorCode.LLM_TIMEOUT,
                "模型调用超时，请稍后重试。",
                package.version,
                package.prompt_hash,
                usage,
            )

    def _build_v1_schema_context(self, question: str, metric_entries: list | None = None) -> SchemaContext:
        """将 V1 静态 Schema 白名单包装为 SchemaContext，供 V3 Prompt Builder 使用。

        提供基础表结构（V1 Sales 15 张表）；同时把当前指标 dependent_columns 涉及
        的表也加入 allowed_schema，确保大模型能看到毛利率、库存、客户等新域的表。
        V4 接入真实检索层后，此方法将被 TwoLevelRetriever.retrieve() 替代。
        """
        from server.domain.sales_scope import select_relevant_tables, ALLOWED_COLUMNS
        from server.search.repository import Candidate, CandidateSource

        relevant = select_relevant_tables(question)

        # 把指标 dependent_columns 所在的表也加入 schema
        extra_tables: dict[str, list[str]] = {}  # table_name -> [col_name, ...]
        if metric_entries:
            for entry in metric_entries:
                for dep in (entry.dependent_columns or []):
                    parts = dep.split(".")
                    if len(parts) == 2:
                        tbl, col = parts
                        extra_tables.setdefault(tbl, []).append(col)
                # 同时扫描 expression 里隐含的表（格式 "table.column"）
                import re
                for match in re.finditer(r'\b(fact_\w+|dim_\w+)\.\w+', entry.expression):
                    tbl = match.group(1)
                    col = match.group(0).split(".")[1]
                    extra_tables.setdefault(tbl, []).append(col)

        tables: list[Candidate] = []
        columns: list[Candidate] = []

        # V1 白名单表
        for table_name in sorted(relevant):
            allowed_cols = ALLOWED_COLUMNS.get(table_name, frozenset())
            tables.append(
                Candidate(
                    doc_id=f"table::{table_name}",
                    object_type="table",
                    score=1.0,
                    source=CandidateSource.BM25,
                    domain="sales",
                    datasource_id=1,
                    payload={"table_name": table_name, "business_name": table_name},
                )
            )
            for col_name in sorted(allowed_cols):
                columns.append(
                    Candidate(
                        doc_id=f"column::{table_name}::{col_name}",
                        object_type="column",
                        score=0.9,
                        source=CandidateSource.BM25,
                        domain="sales",
                        datasource_id=1,
                        payload={
                            "table_name": table_name,
                            "column_name": col_name,
                            "data_type": "text",
                            "is_primary_key": col_name == "id",
                            "foreign_key_ref": None,
                        },
                    )
                )

        # 指标 dependent_columns 额外表（不在 V1 白名单里）
        existing_table_names = {t.payload["table_name"] for t in tables}
        for table_name, dep_cols in sorted(extra_tables.items()):
            if table_name in existing_table_names:
                # 表已存在，只补充缺失的列
                for col_name in sorted(set(dep_cols)):
                    col_id = f"column::{table_name}::{col_name}"
                    if not any(c.doc_id == col_id for c in columns):
                        columns.append(
                            Candidate(
                                doc_id=col_id,
                                object_type="column",
                                score=0.85,
                                source=CandidateSource.BM25,
                                domain="sales",
                                datasource_id=1,
                                payload={
                                    "table_name": table_name,
                                    "column_name": col_name,
                                    "data_type": "numeric",
                                    "is_primary_key": col_name == "id",
                                    "foreign_key_ref": None,
                                },
                            )
                        )
            else:
                # 新表：加入 tables 和所有依赖列
                tables.append(
                    Candidate(
                        doc_id=f"table::{table_name}",
                        object_type="table",
                        score=0.85,
                        source=CandidateSource.BM25,
                        domain="sales",
                        datasource_id=1,
                        payload={"table_name": table_name, "business_name": table_name},
                    )
                )
                existing_table_names.add(table_name)
                for col_name in sorted(set(dep_cols)):
                    columns.append(
                        Candidate(
                            doc_id=f"column::{table_name}::{col_name}",
                            object_type="column",
                            score=0.85,
                            source=CandidateSource.BM25,
                            domain="sales",
                            datasource_id=1,
                            payload={
                                "table_name": table_name,
                                "column_name": col_name,
                                "data_type": "numeric",
                                "is_primary_key": col_name == "id",
                                "foreign_key_ref": None,
                            },
                        )
                    )

        return SchemaContext(tables=tables, columns=columns)

    def _resolve_metric_entries(
        self,
        metric_ids: tuple[str, ...],
        question: str,
    ) -> list:
        """从 SemanticRegistry 解析 MetricEntry 列表。

        metric_ids 来自 assess_scope() 的同义词解析结果。
        如果问题中未识别到任何指标（metric_ids 为空），
        尝试用问题文本从注册表模糊匹配；仍为空则返回空列表（大模型自主判断）。
        """
        entries = []
        for mid in metric_ids:
            entry = self._registry.get(mid)
            if entry:
                entries.append(entry)
            else:
                logger.debug("metric_id '%s' not found in registry, skipping", mid)

        # metric_ids 为空时，不做全量注入（避免 token 爆炸）
        # 只注入敏感度为 False 且域为 sales 的前 5 个作为提示
        if not entries:
            sales_entries = [
                e for e in self._registry.all_metrics()
                if not e.is_sensitive and e.domain == "sales"
            ][:5]
            entries = sales_entries

        return entries

    async def _attempt_generation(
        self,
        request: LLMRequest,
        prompt_version: str,
        prompt_hash: str,
        usage: _Usage,
        semantic_ctx: SemanticContext,
    ) -> QueryOutcome:
        from server.generation.sql import _gateway_error_code, _safe_error_message

        last_code = QueryErrorCode.LLM_PROVIDER_ERROR
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._gateway.complete(request)
                usage.add(response)
                payload = parse_sql_payload(response.output_text)
            except LLMGatewayError as exc:
                last_code = _gateway_error_code(exc.kind)
                if exc.retryable and attempt < self._max_retries:
                    continue
                return self._failure(last_code, _safe_error_message(last_code), prompt_version, prompt_hash, usage)
            except SQLPayloadError as exc:
                last_code = exc.code
                if attempt < self._max_retries:
                    continue
                return self._failure(last_code, _safe_error_message(last_code), prompt_version, prompt_hash, usage)

            return self._success(payload, prompt_version, prompt_hash, usage, semantic_ctx)

        return self._failure(last_code, _safe_error_message(last_code), prompt_version, prompt_hash, usage)

    def _success(
        self,
        payload: object,
        prompt_version: str,
        prompt_hash: str,
        usage: _Usage,
        semantic_ctx: SemanticContext,
    ) -> QueryOutcome:
        from server.generation.sql import SQLGenerationPayload

        assert isinstance(payload, SQLGenerationPayload)

        if payload.action == "generate":
            return QueryOutcome(
                status=QueryStatus.PROCESSING,
                sql=payload.sql,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                model_version=usage.model_version or self.model_version,
                model_parameters=self._gateway.model_parameters,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                provider_request_id=usage.provider_request_id,
            )
        if payload.action == "clarify":
            return QueryOutcome(
                status=QueryStatus.CLARIFICATION_REQUIRED,
                error_code=QueryErrorCode.AMBIGUOUS_METRIC,
                error_message="问题存在歧义，请补充指标口径或查询范围。",
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                model_version=usage.model_version or self.model_version,
                model_parameters=self._gateway.model_parameters,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                provider_request_id=usage.provider_request_id,
            )
        return QueryOutcome(
            status=QueryStatus.REJECTED,
            error_code=QueryErrorCode.OUT_OF_SCOPE,
            error_message="该问题超出当前支持的查询范围。",
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            model_version=usage.model_version or self.model_version,
            model_parameters=self._gateway.model_parameters,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            provider_request_id=usage.provider_request_id,
        )

    def _failure(
        self,
        code: QueryErrorCode,
        message: str,
        prompt_version: str,
        prompt_hash: str,
        usage: _Usage,
    ) -> QueryOutcome:
        return QueryOutcome(
            status=QueryStatus.FAILED,
            error_code=code,
            error_message=message,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            model_version=usage.model_version or self.model_version,
            model_parameters=self._gateway.model_parameters,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            provider_request_id=usage.provider_request_id,
        )
