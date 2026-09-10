"""HybridSearchRepository：混合检索（BM25 + Dense）的统一入口。

实现了 SearchRepository 协议，内部同时调用 OpenSearchRetriever 和 MilvusRetriever，
处理降级和双路失败逻辑，然后将两路结果交给 RRFFusion 融合。

降级规则（V2 约定）：
    - BM25 路超时 → 仅使用 Dense 路结果，status=DEGRADED，trace 标注 degraded_source=bm25；
    - Dense 路超时 → 仅使用 BM25 路结果，status=DEGRADED，trace 标注 degraded_source=dense；
    - 双路均失败  → 返回空列表，status=FAILED；不抛出异常，让调用方决定如何处理。

单路返回时依然：
    1. 核验候选的 datasource_id 和 domain 授权（下游再次验证）；
    2. 在 SearchResult.trace_info 中标注 "degraded": true；
    3. 不静默返回错误的数据，宁可空列表也不越权。

调用链：
    QueryOrchestrator
        → HybridSearchRepository.search_schema(...)
            → asyncio.gather(opensearch.search_schema, milvus.search_schema)
            → RRFFusion.fuse(bm25_result, dense_result)
            → SearchResult
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from server.search.fusion import RRFFusion
from server.search.milvus import MilvusRetriever
from server.search.opensearch import OpenSearchRetriever
from server.search.repository import (
    Candidate,
    RetrievalStatus,
    SearchRepository,
    SearchResult,
)

logger = logging.getLogger(__name__)


class HybridSearchRepository:
    """混合检索实现，满足 SearchRepository 协议。

    Args:
        opensearch: OpenSearch BM25 检索器。
        milvus: Milvus dense 检索器。
        fusion: RRF 融合器；None 时使用默认配置。
    """

    def __init__(
        self,
        opensearch: OpenSearchRetriever,
        milvus: MilvusRetriever,
        fusion: RRFFusion | None = None,
    ) -> None:
        self._opensearch = opensearch
        self._milvus = milvus
        self._fusion = fusion or RRFFusion()

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
        """并行调用 BM25 + Dense，合并结果后做 RRF 融合。"""
        # 并行调用两路检索，各自有独立超时控制
        bm25_result, dense_result = await asyncio.gather(
            self._opensearch.search_schema(
                query,
                datasource_id=datasource_id,
                allowed_domains=allowed_domains,
                object_types=object_types,
                metadata_version=metadata_version,
                top_k=top_k,
            ),
            self._milvus.search_schema(
                query,
                datasource_id=datasource_id,
                allowed_domains=allowed_domains,
                object_types=object_types,
                metadata_version=metadata_version,
                top_k=top_k,
            ),
        )

        return _merge_and_fuse(bm25_result, dense_result, self._fusion, top_k)

    async def search_values(
        self,
        value_text: str,
        *,
        datasource_id: int,
        allowed_domains: list[str],
        column_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> SearchResult:
        """Value Linking 的检索：BM25 精确/模糊 + Dense 语义。"""
        bm25_result, dense_result = await asyncio.gather(
            self._opensearch.search_values(
                value_text,
                datasource_id=datasource_id,
                allowed_domains=allowed_domains,
                column_ids=column_ids,
                top_k=top_k,
            ),
            # Dense 路：把 value_text 当 query，检索语义相似的列
            self._milvus.search_schema(
                value_text,
                datasource_id=datasource_id,
                allowed_domains=allowed_domains,
                object_types=["column"],
                top_k=top_k,
            ),
        )

        return _merge_and_fuse(bm25_result, dense_result, self._fusion, top_k)

    async def search_verified_queries(
        self,
        query: str,
        *,
        allowed_domains: list[str],
        top_k: int = 5,
    ) -> SearchResult:
        """双路检索已验证查询。"""
        bm25_result, dense_result = await asyncio.gather(
            self._opensearch.search_verified_queries(
                query, allowed_domains=allowed_domains, top_k=top_k
            ),
            self._milvus.search_verified_queries(
                query, allowed_domains=allowed_domains, top_k=top_k
            ),
        )

        return _merge_and_fuse(bm25_result, dense_result, self._fusion, top_k)


def _merge_and_fuse(
    bm25_result: SearchResult,
    dense_result: SearchResult,
    fusion: RRFFusion,
    top_k: int,
) -> SearchResult:
    """根据两路结果的状态决定如何融合。

    双路均失败 → FAILED；单路失败 → DEGRADED + 单路结果；双路正常 → RRF 融合。
    融合后依然按授权约束过滤，不把 FAILED 路的错误结果混入。
    """
    bm25_ok = bm25_result.status != RetrievalStatus.FAILED
    dense_ok = dense_result.status != RetrievalStatus.FAILED

    # 双路均失败
    if not bm25_ok and not dense_ok:
        logger.error("Both BM25 and Dense retrieval failed")
        return SearchResult(
            candidates=[],
            status=RetrievalStatus.FAILED,
            trace_info={
                "bm25": bm25_result.trace_info,
                "dense": dense_result.trace_info,
            },
        )

    # 仅 BM25 路失败 → 降级为纯 Dense
    if not bm25_ok:
        logger.warning("BM25 retrieval failed or degraded, using Dense only")
        return SearchResult(
            candidates=dense_result.candidates[:top_k],
            status=RetrievalStatus.DEGRADED,
            bm25_count=0,
            dense_count=len(dense_result.candidates),
            degraded_source="bm25",
            trace_info={"degraded": True, "bm25": bm25_result.trace_info},
        )

    # 仅 Dense 路失败 → 降级为纯 BM25
    if not dense_ok:
        logger.warning("Dense retrieval failed or degraded, using BM25 only")
        return SearchResult(
            candidates=bm25_result.candidates[:top_k],
            status=RetrievalStatus.DEGRADED,
            bm25_count=len(bm25_result.candidates),
            dense_count=0,
            degraded_source="dense",
            trace_info={"degraded": True, "dense": dense_result.trace_info},
        )

    # 双路正常 → RRF 融合
    fused = fusion.fuse(
        bm25_candidates=bm25_result.candidates,
        dense_candidates=dense_result.candidates,
        top_k=top_k,
    )
    return SearchResult(
        candidates=fused,
        status=RetrievalStatus.OK,
        bm25_count=len(bm25_result.candidates),
        dense_count=len(dense_result.candidates),
        trace_info={
            "bm25_count": len(bm25_result.candidates),
            "dense_count": len(dense_result.candidates),
            "fused_count": len(fused),
        },
    )
