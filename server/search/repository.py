"""SearchRepository：统一检索仓储接口与 Candidate 数据契约。

设计原则（依赖倒置）：
    业务层（QueryOrchestrator、SchemaLinker 等）只依赖 SearchRepository 协议，
    不直接调用 opensearch-py 或 pymilvus SDK。底层实现在 opensearch.py / milvus.py 中，
    由依赖注入在应用启动时组装。

    好处：
    - 单测时注入 InMemorySearchRepository，无需启动 OpenSearch / Milvus；
    - 切换底层引擎不影响业务逻辑；
    - 授权过滤、版本过滤集中在 Repository 实现内，业务层不重复。

Candidate 契约（统一格式）：
    无论来自 BM25 还是 dense，都返回 Candidate 对象，包含：
    - doc_id：与 document_id.py 约定一致的稳定标识
    - object_type：table / column / metric / verified_query
    - score：检索得分（BM25 为 BM25 分，dense 为 IP 内积）
    - source：标明来自 bm25 / dense / rrf（融合后）
    - domain、datasource_id 等过滤字段
    - payload：原始文档字段，供 Schema Linking 和 Prompt 构建使用

调用链示意：
    SearchRepository.search_schema(query, domain, datasource_id, top_k)
        → OpenSearchRetriever.search(...) + MilvusRetriever.search(...)
        → [Candidate, ...]（各路结果）
        → RRFFusion.fuse(bm25_candidates, dense_candidates)
        → [Candidate, ...]（融合结果）
        → Reranker.rerank(question, candidates)
        → [Candidate, ...]（最终结果）
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Protocol


class CandidateSource(enum.StrEnum):
    """候选结果的来源。"""

    BM25 = "bm25"
    DENSE = "dense"
    RRF = "rrf"  # RRF 融合后
    RERANKED = "reranked"  # Reranker 重排后


class RetrievalStatus(enum.StrEnum):
    """单次检索调用的状态，用于 Trace 标记。"""

    OK = "ok"
    DEGRADED = "degraded"  # 某一路超时降级，仅返回单路结果
    FAILED = "failed"  # 双路均失败


@dataclass(frozen=True)
class Candidate:
    """统一候选结果契约。

    同一对象可能在多个 source 中出现（bm25 和 dense 都命中），
    融合层（RRF）负责去重并合并为一个 Candidate（source=rrf）。

    Attributes:
        doc_id: 稳定文档 ID，格式见 document_id.py。
        object_type: table / column / metric / verified_query。
        score: 该来源的原始分数；RRF 融合后为 RRF 分。
        source: 结果来源。
        domain: 所属业务域，便于过滤。
        datasource_id: 所属数据源 ID。
        metadata_version: 生成该文档时的元数据版本，检测 stale 用。
        bm25_rank: BM25 路中的排名，去重时保存，用于调试和消融实验。
        dense_rank: Dense 路中的排名。
        payload: 原始文档字段（table_name、business_name、description 等）。
    """

    doc_id: str
    object_type: str
    score: float
    source: CandidateSource
    domain: str = ""
    datasource_id: int = 0
    metadata_version: str = ""
    bm25_rank: int | None = None
    dense_rank: int | None = None
    # 原始文档字段，任意 key-value
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    """一次完整检索调用的结果，包含候选列表和状态信息。

    Attributes:
        candidates: 排序后的候选列表（已去重、已重排）。
        status: 本次检索的整体状态。
        bm25_count: BM25 路命中数量（降级时为 0）。
        dense_count: Dense 路命中数量（降级时为 0）。
        degraded_source: 降级时说明哪一路失败了（"bm25" 或 "dense"）。
        trace_info: 供 Trace 使用的额外诊断信息。
    """

    candidates: list[Candidate]
    status: RetrievalStatus = RetrievalStatus.OK
    bm25_count: int = 0
    dense_count: int = 0
    degraded_source: str | None = None
    trace_info: dict[str, Any] = field(default_factory=dict)


class SearchRepository(Protocol):
    """统一检索仓储协议。

    所有实现必须满足以下约束：
    1. 不向业务层暴露 SDK 类型（opensearch-py / pymilvus）；
    2. 强制传递 datasource_id 和 allowed_domains，防止跨数据源泄露；
    3. 单路超时时降级为单路返回，并在 SearchResult.status 标明 DEGRADED；
    4. 双路均失败时返回空列表 + status=FAILED，不抛出异常。
    """

    async def search_schema(
        self,
        query: str,
        *,
        datasource_id: int,
        allowed_domains: list[str],
        object_types: list[str] | None = None,  # None 表示不过滤类型
        metadata_version: str | None = None,
        top_k: int = 20,
    ) -> SearchResult:
        """检索表和列候选。

        Args:
            query: 用户问题或其提取的关键词片段。
            datasource_id: 限定数据源，防止跨源泄露。
            allowed_domains: 限定业务域列表（域路由结果），空列表表示不限制。
            object_types: 限定对象类型，例如 ["table"] 只召回表。
            metadata_version: 指定元数据版本；None 表示使用最新 PUBLISHED 版本。
            top_k: 每路最多返回的候选数，融合后数量 ≤ top_k。

        Returns:
            SearchResult，包含去重融合后的候选列表和状态信息。
        """
        ...

    async def search_values(
        self,
        value_text: str,
        *,
        datasource_id: int,
        allowed_domains: list[str],
        column_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> SearchResult:
        """检索数据库真实值（用于 Value Linking）。

        Args:
            value_text: 用户表达的实体值，例如"苹果"、"华东"。
            column_ids: 限定在指定列的样例值中检索，None 表示不限制。
        """
        ...

    async def search_verified_queries(
        self,
        query: str,
        *,
        allowed_domains: list[str],
        top_k: int = 5,
    ) -> SearchResult:
        """检索相似的已验证查询（用于 Few-shot SQL 生成）。"""
        ...


class InMemorySearchRepository:
    """离线测试用的内存 SearchRepository。

    直接从 candidates 字典读取，无需 OpenSearch / Milvus。
    通过 register_candidates() 预置测试数据，模拟真实索引。
    """

    def __init__(self) -> None:
        # key: (object_type, datasource_id) → candidates 列表
        self._schema_candidates: list[Candidate] = []
        self._value_candidates: list[Candidate] = []
        self._verified_query_candidates: list[Candidate] = []

    def register_schema_candidates(self, candidates: list[Candidate]) -> None:
        """预置 Schema 候选（测试用）。"""
        self._schema_candidates = list(candidates)

    def register_value_candidates(self, candidates: list[Candidate]) -> None:
        """预置值候选（测试用）。"""
        self._value_candidates = list(candidates)

    def register_verified_query_candidates(self, candidates: list[Candidate]) -> None:
        """预置已验证查询候选（测试用）。"""
        self._verified_query_candidates = list(candidates)

    async def search_schema(
        self,
        query: str,
        *,
        datasource_id: int,
        allowed_domains: list[str],
        object_types: list[str] | None = None,
        metadata_version: str | None = None,
        top_k: int = 20,
    ) -> SearchResult:
        """过滤并返回预置的 Schema 候选。"""
        results = [
            c
            for c in self._schema_candidates
            if c.datasource_id == datasource_id
            and (not allowed_domains or c.domain in allowed_domains)
            and (object_types is None or c.object_type in object_types)
        ]
        # 按 score 降序
        results.sort(key=lambda c: c.score, reverse=True)
        results = results[:top_k]
        return SearchResult(
            candidates=results,
            status=RetrievalStatus.OK,
            bm25_count=len(results),
            dense_count=0,
        )

    async def search_values(
        self,
        value_text: str,
        *,
        datasource_id: int,
        allowed_domains: list[str],
        column_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> SearchResult:
        """返回预置的值候选（简单字符串包含过滤）。"""
        results = [
            c
            for c in self._value_candidates
            if datasource_id == c.datasource_id
            and value_text.lower() in str(c.payload.get("value", "")).lower()
            and (column_ids is None or c.doc_id in column_ids)
        ]
        results.sort(key=lambda c: c.score, reverse=True)
        return SearchResult(candidates=results[:top_k], status=RetrievalStatus.OK)

    async def search_verified_queries(
        self,
        query: str,
        *,
        allowed_domains: list[str],
        top_k: int = 5,
    ) -> SearchResult:
        """返回预置的已验证查询候选。"""
        results = [
            c
            for c in self._verified_query_candidates
            if not allowed_domains or c.domain in allowed_domains
        ]
        results.sort(key=lambda c: c.score, reverse=True)
        return SearchResult(candidates=results[:top_k], status=RetrievalStatus.OK)
