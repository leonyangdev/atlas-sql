"""Milvus Dense 向量检索实现。

负责的职责：
- 将 SearchRepository 的语义查询转换为 Milvus search 调用；
- 强制传递 datasource_id、allowed_domains 等标量过滤条件；
- 单次调用超时由调用方（HybridSearchRepository）控制；
- 不暴露 pymilvus 类型到业务层。

Collection 命名约定（与 milvus_schema.py 一致）：
    {env}_schema           — 表和列的向量索引
    {env}_verified_queries — 已验证查询向量索引

安装依赖：
    uv add "pymilvus>=2.4,<3"

V2 阶段要点：
1. 先调用 EmbeddingProvider 对 query 文本编码，得到 dense 向量；
2. 用 expr 表达式传递标量过滤（datasource_id、domain、metadata_version）；
3. 返回统一 Candidate，score 为 IP 内积（值越高越相似）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from server.llm.embedding import EmbeddingProvider
from server.search.document_id import OBJECT_TYPE_TABLE
from server.search.repository import Candidate, CandidateSource, RetrievalStatus, SearchResult

logger = logging.getLogger(__name__)


class MilvusRetriever:
    """封装 Milvus 的 dense 向量检索。

    Args:
        collection_client: pymilvus Collection 实例（鸭子类型），由应用工厂注入。
        embedding_provider: 用于将查询文本转换为向量。
        env: 环境前缀，用于 collection 命名。
        output_fields: Milvus 返回的标量字段列表。
        timeout_seconds: 单次 search 超时秒数。
    """

    # Milvus 返回的标量字段
    DEFAULT_OUTPUT_FIELDS = [
        "doc_id", "object_type", "domain",
        "datasource_id", "metadata_version", "embedding_model_version",
    ]

    def __init__(
        self,
        collection_client: Any,
        embedding_provider: EmbeddingProvider,
        env: str = "dev",
        output_fields: list[str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = collection_client
        self._embedding = embedding_provider
        self._env = env
        self._output_fields = output_fields or self.DEFAULT_OUTPUT_FIELDS
        self._timeout = timeout_seconds

    def _collection_name(self, coll_type: str) -> str:
        """生成 collection 名称，例如 dev_schema。"""
        return f"{self._env}_{coll_type}"

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
        """Dense 向量检索表和列。

        先将 query 编码为 dense 向量，再在 Milvus 中做 ANN 搜索，
        同时通过 expr 表达式过滤 datasource_id / domain / metadata_version。
        """
        # 编码查询向量（在线程池中执行，避免阻塞事件循环）
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, self._embedding.embed_batch, [query]
            )
            query_vector = results[0].dense
        except Exception as exc:
            logger.error("Embedding failed: %s", exc)
            return SearchResult(
                candidates=[],
                status=RetrievalStatus.FAILED,
                degraded_source="dense",
                trace_info={"error": f"embedding_failed: {exc}"},
            )

        # 构造标量过滤表达式（Milvus expr 语法）
        expr = _build_milvus_expr(
            datasource_id=datasource_id,
            allowed_domains=allowed_domains,
            object_types=object_types,
            metadata_version=metadata_version,
        )

        try:
            search_results = await asyncio.wait_for(
                _milvus_search(
                    client=self._client,
                    collection_name=self._collection_name("schema"),
                    vectors=[query_vector],
                    top_k=top_k,
                    expr=expr,
                    output_fields=self._output_fields,
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Milvus schema search timeout (%.1fs), datasource_id=%d",
                self._timeout, datasource_id,
            )
            return SearchResult(
                candidates=[],
                status=RetrievalStatus.DEGRADED,
                degraded_source="dense",
                trace_info={"reason": "timeout"},
            )
        except Exception as exc:
            logger.error("Milvus schema search error: %s", exc)
            return SearchResult(
                candidates=[],
                status=RetrievalStatus.FAILED,
                degraded_source="dense",
                trace_info={"error": str(exc)},
            )

        candidates = _parse_milvus_results(search_results, source=CandidateSource.DENSE)
        return SearchResult(
            candidates=candidates,
            status=RetrievalStatus.OK,
            dense_count=len(candidates),
        )

    async def search_verified_queries(
        self,
        query: str,
        *,
        allowed_domains: list[str],
        top_k: int = 5,
    ) -> SearchResult:
        """Dense 检索相似的已验证查询。"""
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, self._embedding.embed_batch, [query]
            )
            query_vector = results[0].dense
        except Exception as exc:
            logger.error("Embedding failed for verified_queries: %s", exc)
            return SearchResult(candidates=[], status=RetrievalStatus.FAILED)

        expr = ""
        if allowed_domains:
            domains_str = ", ".join(f'"{d}"' for d in allowed_domains)
            expr = f"domain in [{domains_str}]"

        try:
            search_results = await asyncio.wait_for(
                _milvus_search(
                    client=self._client,
                    collection_name=self._collection_name("verified_queries"),
                    vectors=[query_vector],
                    top_k=top_k,
                    expr=expr,
                    output_fields=self._output_fields,
                ),
                timeout=self._timeout,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning("Milvus verified_queries search error: %s", exc)
            return SearchResult(candidates=[], status=RetrievalStatus.DEGRADED)

        candidates = _parse_milvus_results(search_results, source=CandidateSource.DENSE)
        return SearchResult(candidates=candidates, status=RetrievalStatus.OK)


def _build_milvus_expr(
    datasource_id: int,
    allowed_domains: list[str],
    object_types: list[str] | None,
    metadata_version: str | None,
) -> str:
    """构造 Milvus 标量过滤表达式。

    Milvus expr 语法示例：
        datasource_id == 1 and domain in ["sales", "product"]
    """
    parts: list[str] = [f"datasource_id == {datasource_id}"]

    if allowed_domains:
        domains_str = ", ".join(f'"{d}"' for d in allowed_domains)
        parts.append(f"domain in [{domains_str}]")

    if object_types:
        types_str = ", ".join(f'"{t}"' for t in object_types)
        parts.append(f"object_type in [{types_str}]")

    if metadata_version:
        parts.append(f'metadata_version == "{metadata_version}"')

    return " and ".join(parts)


async def _milvus_search(
    client: Any,
    collection_name: str,
    vectors: list[list[float]],
    top_k: int,
    expr: str,
    output_fields: list[str],
) -> Any:
    """调用 pymilvus Collection.search()（封装为 coroutine）。

    pymilvus 的同步 search() 在线程池中执行，避免阻塞事件循环。
    """
    loop = asyncio.get_event_loop()

    def _sync_search() -> Any:
        return client.search(
            data=vectors,
            anns_field="vector",
            param={"metric_type": "IP", "params": {"ef": 64}},
            limit=top_k,
            expr=expr if expr else None,
            output_fields=output_fields,
        )

    return await loop.run_in_executor(None, _sync_search)


def _parse_milvus_results(results: Any, source: CandidateSource) -> list[Candidate]:
    """从 pymilvus 搜索结果中提取 Candidate 列表。

    pymilvus 结果结构：results[0] 是第一个查询向量的命中列表。
    每个 hit 有 .id（doc_id）、.distance（IP 分数）、.entity 字段。
    """
    candidates: list[Candidate] = []
    if not results:
        return candidates

    # results[0] 对应第一个 query vector（我们只传了一个）
    hits = results[0] if hasattr(results, "__iter__") else []
    for rank, hit in enumerate(hits):
        try:
            # pymilvus Hit 对象
            entity = hit.entity if hasattr(hit, "entity") else {}
            doc_id = str(getattr(hit, "id", "") or entity.get("doc_id", ""))
            score = float(getattr(hit, "distance", 0.0))
            candidates.append(
                Candidate(
                    doc_id=doc_id,
                    object_type=entity.get("object_type", OBJECT_TYPE_TABLE),
                    score=score,
                    source=source,
                    domain=entity.get("domain", ""),
                    datasource_id=int(entity.get("datasource_id") or 0),
                    metadata_version=entity.get("metadata_version", ""),
                    dense_rank=rank + 1,
                    payload=dict(entity) if entity else {},
                )
            )
        except Exception as exc:
            logger.warning("Failed to parse Milvus hit: %s", exc)

    return candidates


class FakeMilvusCollection:
    """测试用的假 Milvus Collection，不发起任何网络请求。

    预置 search 返回结果，支持验证调用参数。
    """

    def __init__(self) -> None:
        self._responses: list[Any] = []
        self.search_calls: list[dict[str, Any]] = []

    def enqueue_response(self, candidates: list[Candidate]) -> None:
        """预置一次 search() 的模拟结果。"""

        class _FakeHit:
            def __init__(self, c: Candidate) -> None:
                self.id = c.doc_id
                self.distance = c.score
                self.entity = {**c.payload, "object_type": c.object_type,
                               "domain": c.domain, "datasource_id": c.datasource_id}

        self._responses.append([_FakeHit(c) for c in candidates])

    def search(self, data: Any, **kwargs: Any) -> Any:
        """返回预置结果，队列为空时返回空列表。"""
        self.search_calls.append({"data": data, **kwargs})
        return [self._responses.pop(0)] if self._responses else [[]]
