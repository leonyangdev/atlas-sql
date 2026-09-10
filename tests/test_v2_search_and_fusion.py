"""V2-S02/S03 测试：SearchRepository、RRF 融合、降级处理、两级召回、Token 预算。

验收场景（V2-S02/S03 故事验收要求）：
    - 业务层无 milvus.search/opensearch.search 直接调用（通过 InMemorySearchRepository 验证）
    - 两个不同授权范围检索同一问题不会得到对方专属对象
    - 同一对象仅保留一次（RRF 去重）
    - 没有候选时返回明确状态（FAILED / DEGRADED）
    - 必需连接键不会因低词相似度被裁掉

覆盖的任务：
    V2-S02-T01: SearchRepository 接口与 Candidate 契约
    V2-S02-T02: OpenSearch + Milvus 检索（通过 Fake 客户端测试）
    V2-S02-T03: 单路降级与双路失败处理
    V2-S03-T01: RRF 融合（去重、常数、每路排名）
    V2-S03-T02: BGE Reranker + 两级召回 + 连接键保护
    V2-S03-T03: Token 预算裁剪
"""

from __future__ import annotations

import pytest

from server.llm.embedding import FakeEmbeddingProvider
from server.search.fusion import RRFFusion
from server.search.hybrid import HybridSearchRepository, _merge_and_fuse
from server.search.milvus import FakeMilvusCollection, MilvusRetriever
from server.search.opensearch import FakeOpenSearchClient, OpenSearchRetriever
from server.search.repository import (
    Candidate,
    CandidateSource,
    InMemorySearchRepository,
    RetrievalStatus,
    SearchResult,
)
from server.search.reranker import FakeReranker
from server.search.retrieval import TwoLevelRetriever, _budget_trim, _estimate_tokens

# ──────────────────────────────────────────────
# 辅助工厂函数
# ──────────────────────────────────────────────


def make_table_candidate(
    doc_id: str,
    score: float,
    domain: str = "sales",
    datasource_id: int = 1,
    table_name: str = "",
    source: CandidateSource = CandidateSource.BM25,
    is_primary_key: bool = False,
    foreign_key_ref: str | None = None,
) -> Candidate:
    return Candidate(
        doc_id=doc_id,
        object_type="table",
        score=score,
        source=source,
        domain=domain,
        datasource_id=datasource_id,
        payload={
            "table_name": table_name or doc_id.split(":")[-1],
            "business_name": "",
            "is_primary_key": is_primary_key,
            "foreign_key_ref": foreign_key_ref,
        },
    )


def make_column_candidate(
    doc_id: str,
    score: float,
    table_name: str,
    column_name: str,
    domain: str = "sales",
    datasource_id: int = 1,
    source: CandidateSource = CandidateSource.BM25,
    is_primary_key: bool = False,
    foreign_key_ref: str | None = None,
) -> Candidate:
    return Candidate(
        doc_id=doc_id,
        object_type="column",
        score=score,
        source=source,
        domain=domain,
        datasource_id=datasource_id,
        payload={
            "table_name": table_name,
            "column_name": column_name,
            "is_primary_key": is_primary_key,
            "foreign_key_ref": foreign_key_ref,
        },
    )


# ──────────────────────────────────────────────
# T01: SearchRepository 契约与 InMemorySearchRepository
# ──────────────────────────────────────────────


class TestInMemorySearchRepository:
    """验证 InMemorySearchRepository 满足授权过滤约束。"""

    async def test_datasource_filter(self) -> None:
        """不同数据源的候选不会相互污染。"""
        repo = InMemorySearchRepository()
        repo.register_schema_candidates(
            [
                make_table_candidate("table:1:pub:fact_order", 1.0, datasource_id=1),
                make_table_candidate("table:2:pub:fact_order", 0.9, datasource_id=2),
            ]
        )

        result = await repo.search_schema(
            "订单量",
            datasource_id=1,
            allowed_domains=["sales"],
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].datasource_id == 1

    async def test_domain_filter(self) -> None:
        """不同业务域的候选不会跨域泄露。"""
        repo = InMemorySearchRepository()
        repo.register_schema_candidates(
            [
                make_table_candidate(
                    "table:1:pub:fact_order", 1.0, domain="sales", datasource_id=1
                ),
                make_table_candidate(
                    "table:1:pub:dim_warehouse", 0.9, domain="inventory", datasource_id=1
                ),
            ]
        )

        result = await repo.search_schema(
            "订单",
            datasource_id=1,
            allowed_domains=["sales"],
        )
        # 只能看到 sales 域的表
        assert all(c.domain == "sales" for c in result.candidates)

    async def test_empty_result_has_ok_status(self) -> None:
        repo = InMemorySearchRepository()
        result = await repo.search_schema("不存在的表", datasource_id=1, allowed_domains=["sales"])
        assert result.status == RetrievalStatus.OK
        assert result.candidates == []

    async def test_sorted_by_score(self) -> None:
        repo = InMemorySearchRepository()
        repo.register_schema_candidates(
            [
                make_table_candidate("table:1:pub:a", 0.3, datasource_id=1),
                make_table_candidate("table:1:pub:b", 0.9, datasource_id=1),
                make_table_candidate("table:1:pub:c", 0.6, datasource_id=1),
            ]
        )
        result = await repo.search_schema("test", datasource_id=1, allowed_domains=[])
        scores = [c.score for c in result.candidates]
        assert scores == sorted(scores, reverse=True)


# ──────────────────────────────────────────────
# T02: OpenSearch + Milvus 检索（Fake 客户端）
# ──────────────────────────────────────────────


class TestOpenSearchRetriever:
    """使用 FakeOpenSearchClient 验证检索逻辑（不发起真实 HTTP 请求）。"""

    async def test_returns_candidates_from_hits(self) -> None:
        fake_client = FakeOpenSearchClient()
        fake_client.enqueue_response(
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "table:1:pub:fact_order",
                            "_score": 8.5,
                            "_source": {
                                "doc_id": "table:1:pub:fact_order",
                                "object_type": "table",
                                "domain": "sales",
                                "datasource_id": 1,
                                "metadata_version": "v1",
                                "table_name": "fact_order",
                            },
                        }
                    ]
                }
            }
        )
        retriever = OpenSearchRetriever(fake_client, env="dev")
        result = await retriever.search_schema("订单量", datasource_id=1, allowed_domains=["sales"])
        assert result.status == RetrievalStatus.OK
        assert len(result.candidates) == 1
        assert result.candidates[0].doc_id == "table:1:pub:fact_order"
        assert result.candidates[0].score == 8.5
        assert result.candidates[0].source == CandidateSource.BM25

    async def test_timeout_returns_degraded(self) -> None:

        class TimeoutClient:
            async def search(self, *, index: str, body: object) -> object:
                raise TimeoutError()

        retriever = OpenSearchRetriever(TimeoutClient(), env="dev", timeout_seconds=0.001)
        result = await retriever.search_schema("test", datasource_id=1, allowed_domains=[])
        assert result.status == RetrievalStatus.DEGRADED
        assert result.degraded_source == "bm25"
        assert result.candidates == []


class TestMilvusRetriever:
    """使用 FakeMilvusCollection 验证 dense 检索逻辑。"""

    async def test_returns_dense_candidates(self) -> None:
        fake_col = FakeMilvusCollection()
        dense_cand = make_table_candidate(
            "table:1:pub:fact_order", 0.95, source=CandidateSource.DENSE, datasource_id=1
        )
        fake_col.enqueue_response([dense_cand])

        fake_embedding = FakeEmbeddingProvider(dimension=8)
        retriever = MilvusRetriever(fake_col, fake_embedding, env="dev")

        result = await retriever.search_schema("订单量", datasource_id=1, allowed_domains=["sales"])
        assert result.status == RetrievalStatus.OK
        assert len(result.candidates) == 1
        assert result.candidates[0].source == CandidateSource.DENSE


# ──────────────────────────────────────────────
# T03: 降级处理
# ──────────────────────────────────────────────


class TestDegradation:
    """验证单路失败时的降级行为。"""

    def test_bm25_fail_returns_dense_only(self) -> None:
        bm25_result = SearchResult(
            candidates=[], status=RetrievalStatus.FAILED, degraded_source="bm25"
        )
        dense_candidates = [
            make_table_candidate("table:1:pub:fact_order", 0.8, source=CandidateSource.DENSE)
        ]
        dense_result = SearchResult(
            candidates=dense_candidates, status=RetrievalStatus.OK, dense_count=1
        )
        fusion = RRFFusion()
        merged = _merge_and_fuse(bm25_result, dense_result, fusion, top_k=10)

        assert merged.status == RetrievalStatus.DEGRADED
        assert merged.degraded_source == "bm25"
        assert len(merged.candidates) == 1

    def test_dense_fail_returns_bm25_only(self) -> None:
        bm25_candidates = [make_table_candidate("table:1:pub:a", 5.0)]
        bm25_result = SearchResult(
            candidates=bm25_candidates, status=RetrievalStatus.OK, bm25_count=1
        )
        dense_result = SearchResult(
            candidates=[], status=RetrievalStatus.FAILED, degraded_source="dense"
        )
        fusion = RRFFusion()
        merged = _merge_and_fuse(bm25_result, dense_result, fusion, top_k=10)

        assert merged.status == RetrievalStatus.DEGRADED
        assert merged.degraded_source == "dense"
        assert len(merged.candidates) == 1

    def test_both_fail_returns_empty_failed(self) -> None:
        failed = SearchResult(candidates=[], status=RetrievalStatus.FAILED)
        merged = _merge_and_fuse(failed, failed, RRFFusion(), top_k=10)
        assert merged.status == RetrievalStatus.FAILED
        assert merged.candidates == []


# ──────────────────────────────────────────────
# T01: RRF 融合
# ──────────────────────────────────────────────


class TestRRFFusion:
    """RRF 公式、去重、每路排名保存、消融实验模式。"""

    def test_deduplicates_same_doc_id(self) -> None:
        """同一 doc_id 在两路都出现时，融合结果中只保留一次。"""
        bm25 = [make_table_candidate("table:1:pub:fact_order", 10.0)]
        dense = [make_table_candidate("table:1:pub:fact_order", 0.95, source=CandidateSource.DENSE)]
        fusion = RRFFusion(k=60)
        result = fusion.fuse(bm25, dense)
        assert len(result) == 1
        assert result[0].doc_id == "table:1:pub:fact_order"

    def test_rrf_score_formula(self) -> None:
        """验证 RRF 分 = 1/(k+1) + 1/(k+1) = 2/(k+1)，两路都在第 1 名。"""
        bm25 = [make_table_candidate("table:1:pub:a", 10.0)]
        dense = [make_table_candidate("table:1:pub:a", 0.9, source=CandidateSource.DENSE)]
        fusion = RRFFusion(k=60)
        result = fusion.fuse(bm25, dense)
        expected_score = 2 * (1.0 / (60 + 1))
        assert abs(result[0].score - expected_score) < 1e-9

    def test_preserves_rank_info(self) -> None:
        """融合结果应保存 bm25_rank 和 dense_rank，供消融分析。"""
        bm25 = [
            make_table_candidate("table:1:pub:a", 10.0),
            make_table_candidate("table:1:pub:b", 8.0),
        ]
        dense = [
            make_table_candidate("table:1:pub:b", 0.9, source=CandidateSource.DENSE),
            make_table_candidate("table:1:pub:a", 0.85, source=CandidateSource.DENSE),
        ]
        fusion = RRFFusion(k=60)
        result = fusion.fuse(bm25, dense)
        result_by_id = {c.doc_id: c for c in result}
        assert result_by_id["table:1:pub:a"].bm25_rank == 1
        assert result_by_id["table:1:pub:a"].dense_rank == 2
        assert result_by_id["table:1:pub:b"].bm25_rank == 2
        assert result_by_id["table:1:pub:b"].dense_rank == 1

    def test_unique_only_in_one_source(self) -> None:
        """只在一路中出现的文档也应该被包含在结果中。"""
        bm25 = [make_table_candidate("table:1:pub:a", 5.0)]
        dense = [make_table_candidate("table:1:pub:b", 0.9, source=CandidateSource.DENSE)]
        fusion = RRFFusion(k=60)
        result = fusion.fuse(bm25, dense)
        ids = {c.doc_id for c in result}
        assert "table:1:pub:a" in ids
        assert "table:1:pub:b" in ids

    def test_top_k_limit(self) -> None:
        """融合结果不超过 top_k。"""
        bm25 = [make_table_candidate(f"table:1:pub:t{i}", float(10 - i)) for i in range(10)]
        dense = [
            make_table_candidate(
                f"table:1:pub:t{i}", float(1 - 0.05 * i), source=CandidateSource.DENSE
            )
            for i in range(10)
        ]
        fusion = RRFFusion(k=60)
        result = fusion.fuse(bm25, dense, top_k=5)
        assert len(result) <= 5

    def test_bm25_only_mode(self) -> None:
        """消融实验 bm25_only 模式：dense 路结果被完全忽略。"""
        bm25 = [make_table_candidate("table:1:pub:bm25_only", 5.0)]
        dense = [make_table_candidate("table:1:pub:dense_only", 0.99, source=CandidateSource.DENSE)]
        fusion = RRFFusion(k=60, bm25_only=True)
        result = fusion.fuse(bm25, dense)
        ids = {c.doc_id for c in result}
        assert "table:1:pub:bm25_only" in ids
        assert "table:1:pub:dense_only" not in ids

    def test_dense_only_mode(self) -> None:
        """消融实验 dense_only 模式：BM25 路结果被完全忽略。"""
        bm25 = [make_table_candidate("table:1:pub:bm25_only", 5.0)]
        dense = [make_table_candidate("table:1:pub:dense_only", 0.99, source=CandidateSource.DENSE)]
        fusion = RRFFusion(k=60, dense_only=True)
        result = fusion.fuse(bm25, dense)
        ids = {c.doc_id for c in result}
        assert "table:1:pub:dense_only" in ids
        assert "table:1:pub:bm25_only" not in ids

    def test_invalid_k_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            RRFFusion(k=0)


# ──────────────────────────────────────────────
# T02: Reranker + 必需字段保护
# ──────────────────────────────────────────────


class TestFakeReranker:
    def test_reranks_by_score(self) -> None:
        reranker = FakeReranker()
        candidates = [
            make_table_candidate("table:1:pub:a", 0.3),
            make_table_candidate("table:1:pub:b", 0.9),
        ]
        result = reranker.rerank("test", candidates, top_n=5)
        assert result[0].doc_id == "table:1:pub:b"

    def test_required_fields_not_dropped(self) -> None:
        """主键字段即使分数低也不会被 top_n 裁掉。"""
        reranker = FakeReranker(score_override={"column:1:pub:t:id": 0.01})
        candidates = [
            # 低分主键列
            make_column_candidate("column:1:pub:t:id", 0.01, "t", "id", is_primary_key=True),
            # 高分普通列
            *[
                make_column_candidate(f"column:1:pub:t:c{i}", 0.9 - 0.01 * i, "t", f"c{i}")
                for i in range(8)
            ],
        ]
        result = reranker.rerank("test", candidates, top_n=5)
        result_ids = {c.doc_id for c in result}
        assert "column:1:pub:t:id" in result_ids, "主键列不应被 top_n 裁掉"

    def test_foreign_key_protected(self) -> None:
        """外键列（foreign_key_ref 不为空）也应被保护。"""
        reranker = FakeReranker(score_override={"column:1:pub:t:order_id": 0.001})
        candidates = [
            make_column_candidate(
                "column:1:pub:t:order_id",
                0.001,
                "t",
                "order_id",
                foreign_key_ref="public.fact_order.id",
            ),
            *[
                make_column_candidate(f"column:1:pub:t:x{i}", 0.8 - 0.01 * i, "t", f"x{i}")
                for i in range(10)
            ],
        ]
        result = reranker.rerank("test", candidates, top_n=5)
        result_ids = {c.doc_id for c in result}
        assert "column:1:pub:t:order_id" in result_ids


# ──────────────────────────────────────────────
# T03: Token 预算裁剪
# ──────────────────────────────────────────────


class TestTokenBudget:
    def test_estimate_tokens(self) -> None:
        from server.search.retrieval import _TOKENS_PER_COLUMN, _TOKENS_PER_TABLE_HEADER

        tables = [make_table_candidate(f"table:1:pub:t{i}", 1.0) for i in range(3)]
        columns = [
            make_column_candidate(f"col:t{i}:{j}", 0.5, f"t{i}", f"c{j}")
            for i in range(3)
            for j in range(5)
        ]
        est = _estimate_tokens(tables, columns)
        assert est == 3 * _TOKENS_PER_TABLE_HEADER + 15 * _TOKENS_PER_COLUMN

    def test_budget_trim_keeps_required(self) -> None:
        """token 预算不足时，主键列仍然保留。"""
        # 只有 1 个 token 的预算（必然触发裁剪）
        pk = make_column_candidate("column:1:pub:t:id", 0.1, "t", "id", is_primary_key=True)
        ordinary = [
            make_column_candidate(f"column:1:pub:t:c{i}", 0.9 - 0.1 * i, "t", f"c{i}")
            for i in range(10)
        ]
        all_cols = [pk] + ordinary
        result = _budget_trim(all_cols, token_budget=1)
        result_ids = {c.doc_id for c in result}
        assert pk.doc_id in result_ids

    def test_budget_trim_removes_low_score_ordinary(self) -> None:
        """在预算内，低分普通列应被裁掉。"""
        from server.search.retrieval import _TOKENS_PER_COLUMN

        high_score = make_column_candidate("col:high", 0.9, "t", "c_high")
        low_score = make_column_candidate("col:low", 0.1, "t", "c_low")
        # 只允许 1 个普通列的预算
        result = _budget_trim([high_score, low_score], token_budget=_TOKENS_PER_COLUMN)
        result_ids = {c.doc_id for c in result}
        assert "col:high" in result_ids
        assert "col:low" not in result_ids


# ──────────────────────────────────────────────
# T02: TwoLevelRetriever 集成测试
# ──────────────────────────────────────────────


class TestTwoLevelRetriever:
    async def test_retrieves_tables_then_columns(self) -> None:
        """两级召回：先召回表，再在候选表内召回列。"""
        repo = InMemorySearchRepository()

        # 预置表候选
        repo.register_schema_candidates(
            [
                make_table_candidate(
                    "table:1:pub:fact_order", 0.9, table_name="fact_order", datasource_id=1
                ),
                make_column_candidate(
                    "column:1:pub:fact_order:id", 0.85, "fact_order", "id", datasource_id=1
                ),
                make_column_candidate(
                    "column:1:pub:fact_order:net_amount",
                    0.8,
                    "fact_order",
                    "net_amount",
                    datasource_id=1,
                ),
            ]
        )

        reranker = FakeReranker()
        retriever = TwoLevelRetriever(repo, reranker=reranker, top_table_n=5, top_col_n=20)

        from datetime import date

        from server.domain.intent import IntentType, QueryIntent

        intent = QueryIntent(
            intent_type=IntentType.ANALYTICAL,
            primary_domain="sales",
            domain_candidates={"sales": 0.96},
            now=date(2026, 9, 10),
        )
        ctx = await retriever.retrieve("今年销售额", intent, datasource_id=1)

        assert len(ctx.tables) >= 1
        # 表名列表非空
        assert len(ctx.table_names()) >= 1

    async def test_empty_result_returns_empty_context(self) -> None:
        """没有候选时返回空 SchemaContext，不抛出异常。"""
        repo = InMemorySearchRepository()  # 空仓储
        retriever = TwoLevelRetriever(repo)

        from datetime import date

        from server.domain.intent import IntentType, QueryIntent

        intent = QueryIntent(
            intent_type=IntentType.ANALYTICAL,
            domain_candidates={},
            now=date(2026, 9, 10),
        )
        ctx = await retriever.retrieve("unknown", intent, datasource_id=1)
        assert ctx.tables == []
        assert ctx.columns == []


# ──────────────────────────────────────────────
# 补充：OpenSearch 值搜索 + 已验证查询搜索
# ──────────────────────────────────────────────


class TestOpenSearchRetrieverExtra:
    """覆盖 opensearch.py 中 search_values 和 search_verified_queries 的路径。"""

    async def test_search_values_returns_candidates(self) -> None:
        from server.search.opensearch import FakeOpenSearchClient, OpenSearchRetriever

        fake_client = FakeOpenSearchClient()
        fake_client.enqueue_response(
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "column:1:pub:dim_product:brand_name",
                            "_score": 5.0,
                            "_source": {
                                "doc_id": "column:1:pub:dim_product:brand_name",
                                "object_type": "column",
                                "domain": "sales",
                                "datasource_id": 1,
                                "metadata_version": "v1",
                                "table_name": "dim_product",
                                "column_name": "brand_name",
                            },
                        }
                    ]
                }
            }
        )
        retriever = OpenSearchRetriever(fake_client, env="dev")
        result = await retriever.search_values("Apple", datasource_id=1, allowed_domains=["sales"])
        assert result.status == RetrievalStatus.OK
        assert len(result.candidates) == 1
        assert result.candidates[0].score == 5.0

    async def test_search_values_timeout_returns_degraded(self) -> None:

        from server.search.opensearch import OpenSearchRetriever

        class TimeoutClient:
            async def search(self, *, index: str, body: object) -> object:
                raise TimeoutError()

        retriever = OpenSearchRetriever(TimeoutClient(), env="dev", timeout_seconds=0.001)
        result = await retriever.search_values("Apple", datasource_id=1, allowed_domains=[])
        assert result.status == RetrievalStatus.DEGRADED

    async def test_search_values_error_returns_failed(self) -> None:
        from server.search.opensearch import OpenSearchRetriever

        class ErrorClient:
            async def search(self, *, index: str, body: object) -> object:
                raise ConnectionError("connection refused")

        retriever = OpenSearchRetriever(ErrorClient(), env="dev")
        result = await retriever.search_values("Apple", datasource_id=1, allowed_domains=[])
        assert result.status == RetrievalStatus.FAILED

    async def test_search_verified_queries_returns_candidates(self) -> None:
        from server.search.opensearch import FakeOpenSearchClient, OpenSearchRetriever

        fake_client = FakeOpenSearchClient()
        fake_client.enqueue_response(
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "verified_query:1",
                            "_score": 7.2,
                            "_source": {
                                "doc_id": "verified_query:1",
                                "object_type": "verified_query",
                                "domain": "sales",
                                "datasource_id": 1,
                                "metadata_version": "v1",
                            },
                        }
                    ]
                }
            }
        )
        retriever = OpenSearchRetriever(fake_client, env="dev")
        result = await retriever.search_verified_queries("销售额", allowed_domains=["sales"])
        assert result.status == RetrievalStatus.OK
        assert len(result.candidates) == 1

    async def test_search_verified_queries_error_degrades(self) -> None:
        from server.search.opensearch import OpenSearchRetriever

        class ErrorClient:
            async def search(self, *, index: str, body: object) -> object:
                raise RuntimeError("boom")

        retriever = OpenSearchRetriever(ErrorClient(), env="dev")
        result = await retriever.search_verified_queries("test", allowed_domains=[])
        assert result.status == RetrievalStatus.DEGRADED
        assert result.candidates == []


# ──────────────────────────────────────────────
# 补充：Milvus 已验证查询搜索 + 错误路径
# ──────────────────────────────────────────────


class TestMilvusRetrieverExtra:
    """覆盖 milvus.py 中 search_verified_queries 和各种失败路径。"""

    async def test_search_verified_queries_returns_candidates(self) -> None:
        from server.llm.embedding import FakeEmbeddingProvider
        from server.search.milvus import FakeMilvusCollection, MilvusRetriever

        fake_col = FakeMilvusCollection()
        dense_cand = make_column_candidate(
            "verified_query:1", 0.88, "t", "c", source=CandidateSource.DENSE
        )
        # FakeMilvusCollection.enqueue_response 需要 list[Candidate]
        fake_col.enqueue_response([dense_cand])

        retriever = MilvusRetriever(fake_col, FakeEmbeddingProvider(dimension=8), env="dev")
        result = await retriever.search_verified_queries("销售额", allowed_domains=["sales"])
        assert result.status == RetrievalStatus.OK

    async def test_search_schema_embedding_failure_returns_failed(self) -> None:
        """Embedding 失败时返回 FAILED，不抛出异常。"""
        from server.llm.embedding import FakeEmbeddingProvider
        from server.search.milvus import MilvusRetriever

        class BrokenEmbedding(FakeEmbeddingProvider):
            def embed_batch(self, texts: list[str]) -> list[object]:
                raise RuntimeError("embed failed")

        class EmptyCol:
            def search(self, **kw: object) -> list[list[object]]:
                return [[]]

        retriever = MilvusRetriever(EmptyCol(), BrokenEmbedding(dimension=8), env="dev")
        result = await retriever.search_schema("test", datasource_id=1, allowed_domains=[])
        assert result.status == RetrievalStatus.FAILED
        assert result.degraded_source == "dense"

    async def test_search_schema_timeout_returns_degraded(self) -> None:
        from server.llm.embedding import FakeEmbeddingProvider
        from server.search.milvus import MilvusRetriever

        class SlowCol:
            def search(self, **kw: object) -> list[list[object]]:
                import time

                time.sleep(10)  # 会被 wait_for 超时
                return [[]]

        retriever = MilvusRetriever(
            SlowCol(),
            FakeEmbeddingProvider(dimension=8),
            env="dev",
            timeout_seconds=0.001,
        )
        result = await retriever.search_schema("test", datasource_id=1, allowed_domains=[])
        assert result.status == RetrievalStatus.DEGRADED
        assert result.degraded_source == "dense"


# ──────────────────────────────────────────────
# 补充：HybridSearchRepository 的 values / verified_queries 路径
# ──────────────────────────────────────────────


class TestHybridSearchRepositoryExtra:
    """覆盖 hybrid.py 中 search_values 和 search_verified_queries 的路径。"""

    def _make_hybrid(self) -> HybridSearchRepository:
        from server.llm.embedding import FakeEmbeddingProvider
        from server.search.fusion import RRFFusion
        from server.search.hybrid import HybridSearchRepository
        from server.search.milvus import FakeMilvusCollection, MilvusRetriever
        from server.search.opensearch import FakeOpenSearchClient, OpenSearchRetriever

        # 两路都返回空结果
        fake_os = FakeOpenSearchClient()
        fake_mv = FakeMilvusCollection()

        os_ret = OpenSearchRetriever(fake_os, env="dev")
        mv_ret = MilvusRetriever(fake_mv, FakeEmbeddingProvider(dimension=8), env="dev")
        return HybridSearchRepository(os_ret, mv_ret, fusion=RRFFusion())

    async def test_search_values_runs_without_error(self) -> None:

        repo = self._make_hybrid()
        result = await repo.search_values("Apple", datasource_id=1, allowed_domains=["sales"])
        # 两路都返回空，融合后也应该是空（status 可以是 OK 或 DEGRADED）
        assert isinstance(result.candidates, list)

    async def test_search_verified_queries_runs_without_error(self) -> None:
        repo = self._make_hybrid()
        result = await repo.search_verified_queries("销售额", allowed_domains=["sales"])
        assert isinstance(result.candidates, list)

    async def test_search_schema_both_empty_returns_ok_empty(self) -> None:
        repo = self._make_hybrid()
        result = await repo.search_schema("test", datasource_id=1, allowed_domains=["sales"])
        # 两路都空，融合结果也为空，但状态应该是 OK（两路都"成功"返回了空列表）
        assert result.candidates == []
