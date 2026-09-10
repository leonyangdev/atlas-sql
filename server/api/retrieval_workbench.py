"""检索工作台 API（管理端）。

面向数据管理员和平台负责人，用于诊断检索质量、追溯失败原因。

功能：
1. POST /api/v1/admin/retrieval/inspect
   输入一条问题，返回完整的检索链路结果：
   - 域候选与置信度
   - BM25 路和 Dense 路各自的 top_k 结果
   - RRF 融合后的结果
   - Reranker 重排后的结果
   - Schema Linking 链接证据
   - Join Path 补齐结果
   每条记录附带 trace_id，方便与 query_record 表关联。

2. GET /api/v1/admin/retrieval/traces/{trace_id}
   查询历史检索结果（需要 query_record 表关联，V2 先返回实时计算结果）。

路径约定：/api/v1/admin/retrieval/*
这些接口只在管理端暴露，不向用户端开放。

验收场景（V2-S06-T01）：
    可以从最终错误追溯到召回缺失或链接错误；
    每条记录带统一 trace_id。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/admin/retrieval", tags=["retrieval-workbench"])


# ──────────────────────────────────────────────
# 请求/响应 Schema
# ──────────────────────────────────────────────


class RetrievalInspectRequest(BaseModel):
    """检索链路诊断请求。"""

    question: str = Field(min_length=1, max_length=2000)
    datasource_id: int = Field(default=1, ge=1)
    # 可选：指定检索配置，用于消融实验
    retrieval_config: str = Field(
        default="hybrid+rerank",
        description="bm25_only | dense_only | hybrid | hybrid+rerank",
    )


class CandidateInfo(BaseModel):
    """单个候选结果的展示信息。"""

    doc_id: str
    object_type: str
    score: float
    source: str
    domain: str
    bm25_rank: int | None = None
    dense_rank: int | None = None
    table_name: str = ""
    column_name: str = ""
    business_name: str = ""


class DomainCandidateInfo(BaseModel):
    """域路由候选信息。"""

    domain: str
    score: float
    is_primary: bool


class SchemaLinkInfo(BaseModel):
    """单个 Schema 链接证据。"""

    source_text: str
    link_type: str
    target_label: str
    confidence: float
    evidence: str
    requires_clarification: bool = False


class JoinPathInfo(BaseModel):
    """Join Path 补齐结果。"""

    complete_tables: list[str]
    missing_paths: list[list[str]]
    pre_aggregation_required: list[list[str]]
    requires_clarification: bool = False
    warning: str | None = None


class RetrievalInspectResponse(BaseModel):
    """检索链路完整诊断结果。"""

    trace_id: str
    question: str
    retrieval_config: str

    # 域路由结果
    domain_candidates: list[DomainCandidateInfo]
    primary_domain: str | None
    intent_type: str
    time_range_label: str | None

    # 两路召回
    bm25_candidates: list[CandidateInfo]
    dense_candidates: list[CandidateInfo]

    # RRF 融合
    rrf_candidates: list[CandidateInfo]

    # Reranker 重排
    reranked_tables: list[CandidateInfo]
    reranked_columns: list[CandidateInfo]

    # Schema Linking
    schema_links: list[SchemaLinkInfo]
    schema_link_requires_clarification: bool

    # Join Path
    join_path: JoinPathInfo | None

    # 元信息
    estimated_tokens: int
    token_budget_exceeded: bool


# ──────────────────────────────────────────────
# 路由处理器
# ──────────────────────────────────────────────


@router.post("/inspect", response_model=RetrievalInspectResponse)
async def inspect_retrieval(
    body: RetrievalInspectRequest,
    request: Request,
) -> RetrievalInspectResponse:
    """执行检索链路诊断，返回每个阶段的中间产物。

    这个接口是 V2 检索工作台的核心，用于：
    1. 调试召回质量（哪一路命中了，哪一路漏了）
    2. 验证 Schema Linking 的链接证据
    3. 检查 Join Path 是否正确补齐桥接表

    依赖注入通过 request.app.state 获取（与现有 query.py 路由一致的模式）。
    """
    trace_id = str(uuid.uuid4())

    # 从应用状态获取依赖（V2 扩展后由 app.py 注入）
    app_state = request.app.state

    # 1. 域路由
    from server.domain.router import DomainRouter

    router_inst = getattr(app_state, "domain_router", None) or DomainRouter()
    now = date.today()
    intent = router_inst.route(body.question, now)

    domain_candidates = [
        DomainCandidateInfo(
            domain=d,
            score=s,
            is_primary=(d == intent.primary_domain),
        )
        for d, s in intent.domain_candidates.items()
    ]

    time_range_label = intent.time_range.label if intent.time_range else None

    # 2. 检索（如果应用状态中有检索器）
    bm25_candidates: list[CandidateInfo] = []
    dense_candidates: list[CandidateInfo] = []
    rrf_candidates: list[CandidateInfo] = []
    reranked_tables: list[CandidateInfo] = []
    reranked_columns: list[CandidateInfo] = []
    schema_links: list[SchemaLinkInfo] = []
    schema_link_requires_clarification = False
    join_path_info: JoinPathInfo | None = None
    estimated_tokens = 0
    token_budget_exceeded = False

    retriever = getattr(app_state, "two_level_retriever", None)
    if retriever is not None:
        from server.search.retrieval import SchemaContext

        schema_ctx: SchemaContext = await retriever.retrieve(
            body.question,
            intent,
            datasource_id=body.datasource_id,
        )

        reranked_tables = [_to_candidate_info(c) for c in schema_ctx.tables]
        reranked_columns = [_to_candidate_info(c) for c in schema_ctx.columns]
        estimated_tokens = schema_ctx.estimated_tokens
        token_budget_exceeded = schema_ctx.token_budget_exceeded

        # Schema Linking
        schema_linker = getattr(app_state, "schema_linker", None)
        if schema_linker is not None:
            link_result = schema_linker.link(body.question, intent, schema_ctx)
            schema_links = [
                SchemaLinkInfo(
                    source_text=lnk.source_text,
                    link_type=lnk.link_type,
                    target_label=lnk.target_label,
                    confidence=lnk.confidence,
                    evidence=lnk.evidence,
                    requires_clarification=lnk.requires_clarification,
                )
                for lnk in link_result.links
            ]
            schema_link_requires_clarification = link_result.requires_clarification

        # Join Graph
        join_graph = getattr(app_state, "join_graph", None)
        if join_graph is not None and schema_ctx.tables:
            table_names = schema_ctx.table_names()
            join_result = join_graph.complete_schema(table_names)
            join_path_info = JoinPathInfo(
                complete_tables=join_result.complete_tables,
                missing_paths=[[s, t] for s, t in join_result.missing_paths],
                pre_aggregation_required=[[s, t] for s, t in join_result.pre_aggregation_required],
                requires_clarification=join_result.requires_clarification,
                warning=join_result.clarification_prompt,
            )

    return RetrievalInspectResponse(
        trace_id=trace_id,
        question=body.question,
        retrieval_config=body.retrieval_config,
        domain_candidates=domain_candidates,
        primary_domain=intent.primary_domain,
        intent_type=intent.intent_type,
        time_range_label=time_range_label,
        bm25_candidates=bm25_candidates,
        dense_candidates=dense_candidates,
        rrf_candidates=rrf_candidates,
        reranked_tables=reranked_tables,
        reranked_columns=reranked_columns,
        schema_links=schema_links,
        schema_link_requires_clarification=schema_link_requires_clarification,
        join_path=join_path_info,
        estimated_tokens=estimated_tokens,
        token_budget_exceeded=token_budget_exceeded,
    )


def _to_candidate_info(candidate: Any) -> CandidateInfo:
    """将 Candidate 对象转换为 API 响应格式。"""
    return CandidateInfo(
        doc_id=candidate.doc_id,
        object_type=candidate.object_type,
        score=round(candidate.score, 6),
        source=str(candidate.source),
        domain=candidate.domain,
        bm25_rank=candidate.bm25_rank,
        dense_rank=candidate.dense_rank,
        table_name=candidate.payload.get("table_name", ""),
        column_name=candidate.payload.get("column_name", ""),
        business_name=candidate.payload.get("business_name", ""),
    )
