"""OpenSearch BM25 / 精确词检索实现。

负责的职责：
- 将 SearchRepository 的业务查询转换为 OpenSearch DSL；
- 强制传递 datasource_id、allowed_domains、metadata_version 过滤条件；
- 单次调用的网络超时由调用方（HybridSearchRepository）控制；
- 不暴露 opensearch-py 类型到 repository.py 或业务层。

索引命名约定（与 opensearch_schema.py 一致）：
    atlas_{env}_schema          — 表和列
    atlas_{env}_metrics         — 指标
    atlas_{env}_verified_queries — 已验证查询

安装依赖：
    uv add "opensearch-py>=2.8,<3"

V2 阶段实现要点：
1. multi_match 覆盖 business_name、description、aliases、physical_name、sample_values；
2. filter 强制加入 datasource_id + domain + metadata_version（如果指定）；
3. 返回统一的 Candidate 列表，score 为 OpenSearch BM25 _score。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from server.search.document_id import OBJECT_TYPE_COLUMN, OBJECT_TYPE_TABLE
from server.search.repository import Candidate, CandidateSource, RetrievalStatus, SearchResult

logger = logging.getLogger(__name__)


class OpenSearchRetriever:
    """封装 OpenSearch 的 BM25 与精确词检索。

    依赖注入 opensearch-py AsyncOpenSearch 客户端；不在此处构造，由应用工厂创建并传入。
    这样测试时可以注入 FakeOpenSearchClient，不依赖真实服务。

    Args:
        client: opensearch-py AsyncOpenSearch 实例（鸭子类型，Protocol 兼容）。
        env: 环境前缀，例如 "dev"、"prod"，用于索引命名。
        timeout_seconds: 单次 HTTP 请求超时秒数。
    """

    def __init__(
        self,
        client: Any,
        env: str = "dev",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client
        self._env = env
        self._timeout = timeout_seconds

    def _index_name(self, index_type: str) -> str:
        """根据环境和索引类型生成索引名称。"""
        return f"atlas_{self._env}_{index_type}"

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
        """BM25 检索表和列。

        使用 multi_match 覆盖多个文本字段，filter 强制限定数据源和业务域，
        确保不同授权范围的用户检索结果不会交叉。
        """
        # 构造 filter 子句（必须满足的条件，不影响 BM25 评分）
        filters: list[dict[str, Any]] = [{"term": {"datasource_id": datasource_id}}]
        if allowed_domains:
            filters.append({"terms": {"domain": allowed_domains}})
        if metadata_version:
            filters.append({"term": {"metadata_version": metadata_version}})
        if object_types:
            filters.append({"terms": {"object_type": object_types}})

        # multi_match 对多字段进行 BM25 评分
        # business_name / aliases 权重较高（^2），sample_values 最低（^0.5）
        must_clause: dict[str, Any] = {
            "multi_match": {
                "query": query,
                "fields": [
                    "business_name^2",
                    "description^1.5",
                    "aliases^2",
                    "physical_name^1",
                    "grain^1",
                    "sample_values^0.5",
                ],
                "type": "best_fields",
                "fuzziness": "AUTO",
                "minimum_should_match": "60%",
            }
        }

        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "must": [must_clause],
                    "filter": filters,
                }
            },
            "size": top_k,
            "_source": True,
        }

        try:
            response = await asyncio.wait_for(
                self._client.search(
                    index=self._index_name("schema"),
                    body=body,
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            logger.warning(
                "OpenSearch schema search timeout (%.1fs), datasource_id=%d",
                self._timeout,
                datasource_id,
            )
            return SearchResult(
                candidates=[],
                status=RetrievalStatus.DEGRADED,
                degraded_source="bm25",
                trace_info={"reason": "timeout"},
            )
        except Exception as exc:
            logger.error("OpenSearch schema search error: %s", exc)
            return SearchResult(
                candidates=[],
                status=RetrievalStatus.FAILED,
                degraded_source="bm25",
                trace_info={"error": str(exc)},
            )

        candidates = _parse_hits(response, source=CandidateSource.BM25)
        return SearchResult(
            candidates=candidates,
            status=RetrievalStatus.OK,
            bm25_count=len(candidates),
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
        """在 sample_values 字段检索真实值（Value Linking 用）。

        优先精确匹配（term），其次 BM25 fuzzy，确保 "Apple" 这类精确品牌名优先排名。
        """
        filters: list[dict[str, Any]] = [
            {"term": {"datasource_id": datasource_id}},
            {"term": {"object_type": OBJECT_TYPE_COLUMN}},
        ]
        if allowed_domains:
            filters.append({"terms": {"domain": allowed_domains}})
        if column_ids:
            filters.append({"terms": {"doc_id": column_ids}})

        # should 中：精确匹配得分更高，模糊匹配作为补充
        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "should": [
                        {
                            "match": {
                                "sample_values": {
                                    "query": value_text,
                                    "boost": 3.0,
                                }
                            }
                        },
                        {
                            "match": {
                                "business_name": {
                                    "query": value_text,
                                    "fuzziness": "AUTO",
                                    "boost": 1.0,
                                }
                            }
                        },
                    ],
                    "filter": filters,
                    "minimum_should_match": 1,
                }
            },
            "size": top_k,
        }

        try:
            response = await asyncio.wait_for(
                self._client.search(
                    index=self._index_name("schema"),
                    body=body,
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            return SearchResult(
                candidates=[],
                status=RetrievalStatus.DEGRADED,
                degraded_source="bm25",
                trace_info={"reason": "timeout"},
            )
        except Exception as exc:
            logger.error("OpenSearch value search error: %s", exc)
            return SearchResult(
                candidates=[],
                status=RetrievalStatus.FAILED,
                degraded_source="bm25",
            )

        candidates = _parse_hits(response, source=CandidateSource.BM25)
        return SearchResult(
            candidates=candidates, status=RetrievalStatus.OK, bm25_count=len(candidates)
        )

    async def search_verified_queries(
        self,
        query: str,
        *,
        allowed_domains: list[str],
        top_k: int = 5,
    ) -> SearchResult:
        """检索已验证查询（用于 Few-shot SQL 生成）。"""
        filters: list[dict[str, Any]] = []
        if allowed_domains:
            filters.append({"terms": {"domain": allowed_domains}})

        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["question^2", "sql_text^1"],
                                "type": "best_fields",
                                "fuzziness": "AUTO",
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "size": top_k,
        }

        try:
            response = await asyncio.wait_for(
                self._client.search(
                    index=self._index_name("verified_queries"),
                    body=body,
                ),
                timeout=self._timeout,
            )
        except (TimeoutError, Exception) as exc:
            logger.warning("OpenSearch verified_queries search error: %s", exc)
            return SearchResult(candidates=[], status=RetrievalStatus.DEGRADED)

        candidates = _parse_hits(response, source=CandidateSource.BM25)
        return SearchResult(candidates=candidates, status=RetrievalStatus.OK)


def _parse_hits(response: dict[str, Any], source: CandidateSource) -> list[Candidate]:
    """从 OpenSearch 响应中提取 Candidate 列表。"""
    hits = response.get("hits", {}).get("hits", [])
    candidates: list[Candidate] = []
    for rank, hit in enumerate(hits):
        doc = hit.get("_source", {})
        doc_id = doc.get("doc_id") or hit.get("_id", "")
        candidates.append(
            Candidate(
                doc_id=doc_id,
                object_type=doc.get("object_type", OBJECT_TYPE_TABLE),
                score=float(hit.get("_score") or 0.0),
                source=source,
                domain=doc.get("domain", ""),
                datasource_id=int(doc.get("datasource_id") or 0),
                metadata_version=doc.get("metadata_version", ""),
                bm25_rank=rank + 1,
                payload=doc,
            )
        )
    return candidates


class FakeOpenSearchClient:
    """测试用的假 OpenSearch 客户端，不发起任何 HTTP 请求。

    search() 直接返回预置的 responses，顺序消费。
    """

    def __init__(self) -> None:
        self._responses: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []

    def enqueue_response(self, response: dict[str, Any]) -> None:
        """预置一次 search() 返回值。"""
        self._responses.append(response)

    async def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        """消费预置响应；队列为空时返回空结果。"""
        self.search_calls.append({"index": index, "body": body})
        if self._responses:
            return self._responses.pop(0)
        return {"hits": {"hits": [], "total": {"value": 0}}}
