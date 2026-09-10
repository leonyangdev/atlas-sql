"""V2 覆盖率补齐测试。

覆盖以下低覆盖模块中的剩余分支：
    - server/api/retrieval_workbench.py（FastAPI 路由 ASGI 测试）
    - server/search/index_status.py（ORM 类 + 枚举导入）
    - server/search/retrieval.py（to_prompt_schema、带 reranker 的列召回、metadata_version 传递）
    - server/search/reranker.py（_build_document_text、BGEReranker import 错误）
    - server/linking/join_graph.py（build_graph_from_foreign_keys、孤立节点）
    - server/linking/schema.py（get_linked_metric_ids、get_linked_columns 辅助方法）
    - server/linking/value.py（_infer_value_type、intent_domains_from_context）
    - server/observability/failure.py（FailureClassifier 各分支）
    - server/api/trace.py（trace 路由）
"""

from __future__ import annotations

from datetime import date

import pytest

from server.domain.query import QueryErrorCode
from server.search.repository import Candidate, CandidateSource, InMemorySearchRepository
from server.search.reranker import FakeReranker
from server.search.retrieval import SchemaContext, TwoLevelRetriever

# ──────────────────────────────────────────────
# search/index_status.py — 导入 ORM 即可覆盖
# ──────────────────────────────────────────────


class TestIndexStatus:
    def test_enum_values_defined(self) -> None:
        from server.search.index_status import IndexBatchStatus

        assert IndexBatchStatus.PENDING == "pending"
        assert IndexBatchStatus.BUILDING == "building"
        assert IndexBatchStatus.PUBLISHED == "published"
        assert IndexBatchStatus.FAILED == "failed"

    def test_orm_classes_importable(self) -> None:
        from server.search.index_status import IndexBatch, PublishedIndexVersion

        # 类名和 __tablename__ 正确
        assert IndexBatch.__tablename__ == "index_batch"
        assert PublishedIndexVersion.__tablename__ == "published_index_version"

    def test_index_batch_has_required_columns(self) -> None:
        from server.search.index_status import IndexBatch

        cols = {c.key for c in IndexBatch.__table__.columns}
        assert "id" in cols
        assert "index_type" in cols
        assert "status" in cols
        assert "batch_key" in cols

    def test_published_index_version_has_required_columns(self) -> None:
        from server.search.index_status import PublishedIndexVersion

        cols = {c.key for c in PublishedIndexVersion.__table__.columns}
        assert "index_type" in cols
        assert "index_batch_id" in cols
        assert "embedding_model_version" in cols


# ──────────────────────────────────────────────
# search/retrieval.py — to_prompt_schema、列召回路径
# ──────────────────────────────────────────────


def _make_table_c(table_name: str) -> Candidate:
    return Candidate(
        doc_id=f"table:1:pub:{table_name}",
        object_type="table",
        score=0.9,
        source=CandidateSource.RRF,
        domain="sales",
        datasource_id=1,
        payload={
            "table_name": table_name,
            "business_name": f"{table_name}_business",
            "description": "desc",
            "domain": "sales",
        },
    )


def _make_col_c(table_name: str, col_name: str, is_pk: bool = False) -> Candidate:
    return Candidate(
        doc_id=f"column:1:pub:{table_name}:{col_name}",
        object_type="column",
        score=0.8,
        source=CandidateSource.RRF,
        domain="sales",
        datasource_id=1,
        payload={
            "table_name": table_name,
            "column_name": col_name,
            "data_type": "varchar",
            "business_name": col_name,
            "description": "",
            "is_primary_key": is_pk,
            "foreign_key_ref": None,
        },
    )


class TestSchemaContextPromptSchema:
    def test_to_prompt_schema_basic(self) -> None:
        ctx = SchemaContext(
            tables=[_make_table_c("fact_order")],
            columns=[
                _make_col_c("fact_order", "id", is_pk=True),
                _make_col_c("fact_order", "net_amount"),
            ],
        )
        schema = ctx.to_prompt_schema()
        assert len(schema) == 1
        table_entry = schema[0]
        assert table_entry["table_name"] == "fact_order"
        assert len(table_entry["columns"]) == 2  # type: ignore[arg-type]

    def test_to_prompt_schema_pk_flag_preserved(self) -> None:
        ctx = SchemaContext(
            tables=[_make_table_c("fact_order")],
            columns=[_make_col_c("fact_order", "id", is_pk=True)],
        )
        col_entry = ctx.to_prompt_schema()[0]["columns"][0]  # type: ignore[index]
        assert col_entry["is_primary_key"] is True

    def test_to_prompt_schema_empty_context(self) -> None:
        ctx = SchemaContext()
        assert ctx.to_prompt_schema() == []

    def test_to_prompt_schema_column_without_matching_table(self) -> None:
        """列属于不在 tables 中的表时，该列不出现在任何表的 columns 里。"""
        ctx = SchemaContext(
            tables=[_make_table_c("fact_order")],
            columns=[_make_col_c("dim_region", "region_name")],  # 不在 tables 里
        )
        schema = ctx.to_prompt_schema()
        assert schema[0]["columns"] == []  # type: ignore[index]

    def test_table_names_returns_list(self) -> None:
        ctx = SchemaContext(tables=[_make_table_c("fact_order"), _make_table_c("dim_store")])
        names = ctx.table_names()
        assert "fact_order" in names
        assert "dim_store" in names


class TestTwoLevelRetrieverColumnPath:
    """覆盖 retrieval.py 77-104 行（列召回 + metadata_version + token 预算触发）。"""

    async def test_retrieve_with_metadata_version(self) -> None:
        """传递 metadata_version 不会报错。"""
        repo = InMemorySearchRepository()
        repo.register_schema_candidates(
            [
                _make_table_c("fact_order"),
                _make_col_c("fact_order", "net_amount"),
            ]
        )
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        from server.domain.intent import IntentType, QueryIntent

        intent = QueryIntent(
            intent_type=IntentType.ANALYTICAL,
            domain_candidates={"sales": 0.9},
            now=date(2026, 9, 10),
        )
        ctx = await retriever.retrieve("销售额", intent, datasource_id=1, metadata_version="v1")
        assert isinstance(ctx, SchemaContext)

    async def test_retrieve_triggers_token_budget(self) -> None:
        """token_budget 非常小时触发裁剪，应完成而不报错。"""
        repo = InMemorySearchRepository()
        # 注册很多列，触发 token 预算
        candidates = [_make_table_c("fact_order")]
        for i in range(50):
            candidates.append(_make_col_c("fact_order", f"col_{i}"))
        repo.register_schema_candidates(candidates)

        # token_budget=1 强制触发裁剪
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker(), token_budget=1)
        from server.domain.intent import IntentType, QueryIntent

        intent = QueryIntent(
            intent_type=IntentType.ANALYTICAL,
            domain_candidates={"sales": 0.9},
            now=date(2026, 9, 10),
        )
        ctx = await retriever.retrieve("销售额", intent, datasource_id=1)
        assert ctx.token_budget_exceeded is True

    async def test_retrieve_no_reranker_still_works(self) -> None:
        """不配置 reranker 时走 else 分支（candidates[:top_n]）。"""
        repo = InMemorySearchRepository()
        repo.register_schema_candidates([_make_table_c("fact_order")])
        retriever = TwoLevelRetriever(repo, reranker=None)  # 不传 reranker
        from server.domain.intent import IntentType, QueryIntent

        intent = QueryIntent(
            intent_type=IntentType.ANALYTICAL,
            domain_candidates={"sales": 0.9},
            now=date(2026, 9, 10),
        )
        ctx = await retriever.retrieve("销售额", intent, datasource_id=1)
        assert isinstance(ctx, SchemaContext)

    async def test_retrieve_config_label_preserved(self) -> None:
        """retrieval_config 标签写入 SchemaContext。"""
        repo = InMemorySearchRepository()
        retriever = TwoLevelRetriever(repo, reranker=FakeReranker())
        from server.domain.intent import IntentType, QueryIntent

        intent = QueryIntent(
            intent_type=IntentType.ANALYTICAL, domain_candidates={}, now=date(2026, 9, 10)
        )
        ctx = await retriever.retrieve(
            "test", intent, datasource_id=1, retrieval_config="bm25_only"
        )
        assert ctx.retrieval_config == "bm25_only"


# ──────────────────────────────────────────────
# search/reranker.py — _build_document_text、BGEReranker import error
# ──────────────────────────────────────────────


class TestBaseRerankerBuildText:
    def test_full_payload(self) -> None:
        """所有字段都有时，text 包含 business_name 等。"""
        from server.search.reranker import FakeReranker

        reranker = FakeReranker()
        c = Candidate(
            doc_id="table:1:pub:fact_order",
            object_type="table",
            score=0.9,
            source=CandidateSource.RRF,
            domain="sales",
            datasource_id=1,
            payload={
                "business_name": "订单事实表",
                "table_name": "fact_order",
                "description": "每行代表一个订单",
                "grain": "订单粒度",
                "aliases": "order,订单",
            },
        )
        text = reranker._build_document_text(c)
        assert "订单事实表" in text
        assert "fact_order" in text

    def test_empty_payload_falls_back_to_doc_id(self) -> None:
        from server.search.reranker import FakeReranker

        reranker = FakeReranker()
        c = Candidate(
            doc_id="table:1:pub:unknown",
            object_type="table",
            score=0.5,
            source=CandidateSource.BM25,
            domain="sales",
            datasource_id=1,
            payload={},
        )
        text = reranker._build_document_text(c)
        assert text == "table:1:pub:unknown"

    def test_partial_payload(self) -> None:
        from server.search.reranker import FakeReranker

        reranker = FakeReranker()
        c = Candidate(
            doc_id="col:x",
            object_type="column",
            score=0.7,
            source=CandidateSource.DENSE,
            domain="sales",
            datasource_id=1,
            payload={"table_name": "fact_order"},
        )
        text = reranker._build_document_text(c)
        assert "fact_order" in text

    def test_bge_reranker_raises_without_flagembedding(self) -> None:
        """没有安装 FlagEmbedding 时，BGEReranker 应抛出有意义的 RuntimeError。"""
        import sys
        from unittest.mock import patch

        with patch.dict(sys.modules, {"FlagEmbedding": None}):
            with pytest.raises((RuntimeError, ImportError)):
                from server.search.reranker import BGEReranker

                BGEReranker()


# ──────────────────────────────────────────────
# linking/join_graph.py — build_graph_from_foreign_keys、has_table、node/edge 计数
# ──────────────────────────────────────────────


class TestJoinGraphHelpers:
    def test_has_table_true(self) -> None:
        from server.linking.join_graph import (
            JoinGraph,
            RelationshipCardinality,
            RelationshipPurpose,
            _FakeRelationship,
        )

        rel = _FakeRelationship(
            id=1,
            from_table="a",
            to_table="b",
            from_column="id",
            to_column="a_id",
            cardinality=RelationshipCardinality.MANY_TO_ONE,
            purpose=RelationshipPurpose.JOIN,
        )
        graph = JoinGraph.load_from_records([rel])
        assert graph.has_table("a") is True
        assert graph.has_table("b") is True

    def test_has_table_false(self) -> None:
        from server.linking.join_graph import JoinGraph

        graph = JoinGraph()
        assert graph.has_table("nonexistent") is False

    def test_node_and_edge_count_empty(self) -> None:
        from server.linking.join_graph import JoinGraph

        graph = JoinGraph()
        assert graph.node_count == 0
        assert graph.edge_count == 0

    def test_build_graph_from_foreign_keys(self) -> None:
        """build_graph_from_foreign_keys 从 ColumnMetadata-like 对象构建图。"""
        from server.linking.join_graph import build_graph_from_foreign_keys

        class FakeTable:
            table_name = "fact_order_item"

        class FakeCol:
            column_name = "order_id"
            foreign_key_ref = "public.fact_order.id"
            table = FakeTable()

        class FakeColNoRef:
            column_name = "net_amount"
            foreign_key_ref = None
            table = FakeTable()

        class FakeColBadRef:
            column_name = "bad_col"
            foreign_key_ref = "invalid"  # 不是 3 段格式
            table = FakeTable()

        graph = build_graph_from_foreign_keys([FakeCol(), FakeColNoRef(), FakeColBadRef()])
        # 只有 FakeCol 应被加入图
        assert graph.node_count == 2  # fact_order_item + fact_order
        assert graph.edge_count == 1

    def test_same_source_target_returns_trivial_path(self) -> None:
        """source == target 时返回只含自己的路径。"""
        from server.linking.join_graph import (
            JoinGraph,
            RelationshipCardinality,
            RelationshipPurpose,
            _FakeRelationship,
        )

        rel = _FakeRelationship(
            id=1,
            from_table="a",
            to_table="b",
            from_column="id",
            to_column="a_id",
            cardinality=RelationshipCardinality.MANY_TO_ONE,
            purpose=RelationshipPurpose.JOIN,
        )
        graph = JoinGraph.load_from_records([rel])
        paths = graph.find_paths("a", "a")
        assert len(paths) == 1
        assert paths[0].tables == ["a"]


# ──────────────────────────────────────────────
# linking/schema.py — get_linked_metric_ids、get_linked_columns
# ──────────────────────────────────────────────


class TestSchemaLinkResultHelpers:
    def test_get_linked_metric_ids(self) -> None:
        from server.linking.schema import LinkType, SchemaLink, SchemaLinkResult

        result = SchemaLinkResult(
            links=[
                SchemaLink(
                    source_text="销售额",
                    link_type=LinkType.METRIC,
                    target_id="metric:net_sales",
                    target_label="net_sales",
                    confidence=0.95,
                    evidence="alias",
                ),
                SchemaLink(
                    source_text="区域",
                    link_type=LinkType.COLUMN,
                    target_id="column:1:pub:dim_region:name",
                    target_label="dim_region.name",
                    confidence=0.85,
                    evidence="match",
                ),
            ]
        )
        ids = result.get_linked_metric_ids()
        assert ids == ["net_sales"]

    def test_get_linked_columns(self) -> None:
        from server.linking.schema import LinkType, SchemaLink, SchemaLinkResult

        result = SchemaLinkResult(
            links=[
                SchemaLink(
                    source_text="区域",
                    link_type=LinkType.COLUMN,
                    target_id="col:x",
                    target_label="dim_region.region_name",
                    confidence=0.85,
                    evidence="match",
                ),
            ]
        )
        cols = result.get_linked_columns()
        assert ("dim_region", "region_name") in cols

    def test_get_linked_metric_ids_empty(self) -> None:
        from server.linking.schema import SchemaLinkResult

        assert SchemaLinkResult().get_linked_metric_ids() == []

    def test_get_linked_columns_bad_label(self) -> None:
        """target_label 格式不对（不含点）时，不应出现在结果中。"""
        from server.linking.schema import LinkType, SchemaLink, SchemaLinkResult

        result = SchemaLinkResult(
            links=[
                SchemaLink(
                    source_text="x",
                    link_type=LinkType.COLUMN,
                    target_id="col:x",
                    target_label="no_dot_here",
                    confidence=0.8,
                    evidence="match",
                ),
            ]
        )
        assert result.get_linked_columns() == []


# ──────────────────────────────────────────────
# linking/value.py — _infer_value_type、intent_domains_from_context
# ──────────────────────────────────────────────


class TestValueLinkingHelpers:
    def test_infer_value_type_integer(self) -> None:
        from server.linking.value import _infer_value_type

        assert _infer_value_type("integer") == "integer"
        assert _infer_value_type("bigint") == "integer"
        assert _infer_value_type("smallint") == "integer"

    def test_infer_value_type_number(self) -> None:
        from server.linking.value import _infer_value_type

        assert _infer_value_type("numeric(10,2)") == "number"
        assert _infer_value_type("float") == "number"
        assert _infer_value_type("double precision") == "number"

    def test_infer_value_type_date(self) -> None:
        from server.linking.value import _infer_value_type

        assert _infer_value_type("date") == "date"
        assert _infer_value_type("timestamp") == "date"
        assert _infer_value_type("timestamptz") == "date"

    def test_infer_value_type_boolean(self) -> None:
        from server.linking.value import _infer_value_type

        assert _infer_value_type("boolean") == "boolean"
        assert _infer_value_type("bool") == "boolean"

    def test_infer_value_type_default_string(self) -> None:
        from server.linking.value import _infer_value_type

        assert _infer_value_type("varchar(128)") == "string"
        assert _infer_value_type("text") == "string"
        assert _infer_value_type("unknown_type") == "string"

    def test_intent_domains_from_context(self) -> None:
        from server.linking.value import intent_domains_from_context

        ctx = SchemaContext(
            tables=[
                Candidate(
                    doc_id="t1",
                    object_type="table",
                    score=0.9,
                    source=CandidateSource.RRF,
                    domain="sales",
                    datasource_id=1,
                ),
                Candidate(
                    doc_id="t2",
                    object_type="table",
                    score=0.8,
                    source=CandidateSource.RRF,
                    domain="product",
                    datasource_id=1,
                ),
            ]
        )
        domains = intent_domains_from_context(ctx)
        assert "sales" in domains
        assert "product" in domains

    def test_intent_domains_from_context_empty(self) -> None:
        from server.linking.value import intent_domains_from_context

        assert intent_domains_from_context(SchemaContext()) == set()


# ──────────────────────────────────────────────
# observability/failure.py — FailureClassifier
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# observability/failure.py — suggest_failure_category 各分支
# ──────────────────────────────────────────────


class TestSuggestFailureCategory:
    """覆盖 failure.py 中 suggest_failure_category 的各分支。"""

    def _make_response(
        self, error_code: QueryErrorCode | None = None, referenced_tables: list[str] | None = None
    ) -> object:
        from unittest.mock import MagicMock

        from server.domain.query import QueryResponse

        resp = MagicMock(spec=QueryResponse)
        if error_code is not None:
            resp.error = MagicMock()
            resp.error.code = error_code
        else:
            resp.error = None
        resp.referenced_tables = referenced_tables or []
        return resp

    def _make_question(
        self, category: str = "analytical", required_tables: list[str] | None = None
    ) -> object:
        from unittest.mock import MagicMock

        q = MagicMock()
        q.category = category
        q.required_tables = required_tables or []
        return q

    def test_sql_parse_error_returns_syntax(self) -> None:
        from server.domain.query import QueryErrorCode
        from server.observability.failure import FailureCategory, suggest_failure_category

        resp = self._make_response(QueryErrorCode.SQL_PARSE_ERROR)
        q = self._make_question()
        assert suggest_failure_category(resp, q) == FailureCategory.SYNTAX_ERROR  # type: ignore[arg-type]

    def test_sql_out_of_scope_wrong_table(self) -> None:
        from server.domain.query import QueryErrorCode
        from server.observability.failure import FailureCategory, suggest_failure_category

        resp = self._make_response(
            QueryErrorCode.SQL_OUT_OF_SCOPE,
            referenced_tables=["wrong_table"],
        )
        q = self._make_question(required_tables=["fact_order"])
        assert suggest_failure_category(resp, q) == FailureCategory.WRONG_TABLE  # type: ignore[arg-type]

    def test_sql_out_of_scope_wrong_column(self) -> None:
        from server.domain.query import QueryErrorCode
        from server.observability.failure import FailureCategory, suggest_failure_category

        # 没有引用任何表，归为 WRONG_COLUMN
        resp = self._make_response(QueryErrorCode.SQL_OUT_OF_SCOPE, referenced_tables=[])
        q = self._make_question(required_tables=["fact_order"])
        assert suggest_failure_category(resp, q) == FailureCategory.WRONG_COLUMN  # type: ignore[arg-type]

    def test_join_category(self) -> None:
        from server.observability.failure import FailureCategory, suggest_failure_category

        resp = self._make_response()
        q = self._make_question(category="join")
        assert suggest_failure_category(resp, q) == FailureCategory.WRONG_JOIN  # type: ignore[arg-type]

    def test_time_category(self) -> None:
        from server.observability.failure import FailureCategory, suggest_failure_category

        resp = self._make_response()
        q = self._make_question(category="time_comparison")
        assert suggest_failure_category(resp, q) == FailureCategory.WRONG_TIME  # type: ignore[arg-type]

    def test_value_category(self) -> None:
        from server.observability.failure import FailureCategory, suggest_failure_category

        resp = self._make_response()
        q = self._make_question(category="value_mapping")
        assert suggest_failure_category(resp, q) == FailureCategory.WRONG_VALUE  # type: ignore[arg-type]

    def test_metric_category(self) -> None:
        from server.observability.failure import FailureCategory, suggest_failure_category

        resp = self._make_response()
        q = self._make_question(category="metric")
        assert suggest_failure_category(resp, q) == FailureCategory.WRONG_METRIC  # type: ignore[arg-type]

    def test_aggregation_category(self) -> None:
        from server.observability.failure import FailureCategory, suggest_failure_category

        resp = self._make_response()
        q = self._make_question(category="top_n")
        assert suggest_failure_category(resp, q) == FailureCategory.WRONG_AGGREGATION  # type: ignore[arg-type]

    def test_unknown_category_returns_undetermined(self) -> None:
        from server.observability.failure import FailureCategory, suggest_failure_category

        resp = self._make_response()
        q = self._make_question(category="unknown_xyz")
        assert suggest_failure_category(resp, q) == FailureCategory.UNDETERMINED  # type: ignore[arg-type]


# ──────────────────────────────────────────────
# api/retrieval_workbench.py — FastAPI ASGI 测试
# ──────────────────────────────────────────────


class TestRetrievalWorkbenchAPI:
    """通过 ASGI 测试检索工作台路由，覆盖 retrieval_workbench.py 全路径。"""

    def _make_app(self) -> object:
        """构造最小 FastAPI 应用，挂载检索工作台路由。"""
        from fastapi import FastAPI

        from server.api.retrieval_workbench import router

        app = FastAPI()
        app.include_router(router)
        return app

    async def test_inspect_returns_200(self) -> None:
        import httpx
        from fastapi import FastAPI

        from server.api.retrieval_workbench import router

        app = FastAPI()
        app.include_router(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/admin/retrieval/inspect",
                json={"question": "今年销售额", "datasource_id": 1},
            )
        assert response.status_code == 200

    async def test_inspect_response_has_trace_id(self) -> None:
        import httpx
        from fastapi import FastAPI

        from server.api.retrieval_workbench import router

        app = FastAPI()
        app.include_router(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/admin/retrieval/inspect",
                json={"question": "今年销售额"},
            )
        body = response.json()
        assert "trace_id" in body
        # trace_id 应该是有效的 UUID 格式
        import uuid

        uuid.UUID(body["trace_id"])  # 不抛出即通过

    async def test_inspect_response_structure(self) -> None:
        """验证响应体包含所有必要字段。"""
        import httpx
        from fastapi import FastAPI

        from server.api.retrieval_workbench import router

        app = FastAPI()
        app.include_router(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/admin/retrieval/inspect",
                json={"question": "华东区域今年销售额", "datasource_id": 1},
            )
        body = response.json()
        required_fields = [
            "trace_id",
            "question",
            "retrieval_config",
            "domain_candidates",
            "primary_domain",
            "intent_type",
            "bm25_candidates",
            "dense_candidates",
            "rrf_candidates",
            "reranked_tables",
            "reranked_columns",
            "schema_links",
            "schema_link_requires_clarification",
            "estimated_tokens",
            "token_budget_exceeded",
        ]
        for field in required_fields:
            assert field in body, f"响应缺少字段：{field}"

    async def test_inspect_domain_routing_in_response(self) -> None:
        """domain_candidates 应包含路由结果。"""
        import httpx
        from fastapi import FastAPI

        from server.api.retrieval_workbench import router

        app = FastAPI()
        app.include_router(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/admin/retrieval/inspect",
                json={"question": "今年销售额"},
            )
        body = response.json()
        # 销售额问题应路由到 sales 域
        assert body["primary_domain"] == "sales"
        domain_names = {d["domain"] for d in body["domain_candidates"]}
        assert "sales" in domain_names

    async def test_inspect_invalid_question_returns_422(self) -> None:
        """空 question 应返回 422 校验错误。"""
        import httpx
        from fastapi import FastAPI

        from server.api.retrieval_workbench import router

        app = FastAPI()
        app.include_router(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/admin/retrieval/inspect",
                json={"question": ""},
            )
        assert response.status_code == 422

    async def test_inspect_with_retrieval_config(self) -> None:
        """retrieval_config 字段应写入响应。"""
        import httpx
        from fastapi import FastAPI

        from server.api.retrieval_workbench import router

        app = FastAPI()
        app.include_router(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/admin/retrieval/inspect",
                json={"question": "销售额", "retrieval_config": "bm25_only"},
            )
        body = response.json()
        assert body["retrieval_config"] == "bm25_only"


# ──────────────────────────────────────────────
# 精细补齐：milvus _parse_milvus_results 异常分支、
#           repository InMemorySearchRepository.search_verified_queries、
#           reranker BGEReranker empty-candidates 路径
# ──────────────────────────────────────────────


class TestMilvusParseBadHit:
    def test_hit_without_entity_attr_parses_with_empty_payload(self) -> None:
        """没有 entity 属性的 hit 被解析为空 payload 的 Candidate，不抛出。"""
        from server.search.milvus import _parse_milvus_results

        class MinimalHit:
            id = "table:1:pub:fact_order"
            distance = 0.8
            # 没有 entity 属性

        results = [[MinimalHit()]]
        candidates = _parse_milvus_results(results, CandidateSource.DENSE)
        assert len(candidates) == 1
        assert candidates[0].doc_id == "table:1:pub:fact_order"
        assert candidates[0].payload == {}

    def test_hit_with_invalid_distance_defaults_to_zero(self) -> None:
        """distance 属性不存在时得分默认为 0.0。"""
        from server.search.milvus import _parse_milvus_results

        class HitNoDistance:
            id = "col:x"
            entity: dict[str, object] = {
                "object_type": "column",
                "domain": "sales",
                "datasource_id": 1,
            }

        results = [[HitNoDistance()]]
        candidates = _parse_milvus_results(results, CandidateSource.DENSE)
        assert len(candidates) == 1
        assert candidates[0].score == 0.0

    def test_empty_results_returns_empty(self) -> None:
        from server.search.milvus import _parse_milvus_results

        assert _parse_milvus_results([], CandidateSource.DENSE) == []

    def test_results_with_none_results_list(self) -> None:
        from server.search.milvus import _parse_milvus_results

        # results[0] 为空列表时
        assert _parse_milvus_results([[]], CandidateSource.DENSE) == []


class TestInMemoryVerifiedQueries:
    async def test_search_verified_queries_filtered_by_domain(self) -> None:
        repo = InMemorySearchRepository()
        repo.register_verified_query_candidates(
            [
                Candidate(
                    doc_id="vq:1",
                    object_type="verified_query",
                    score=0.9,
                    source=CandidateSource.BM25,
                    domain="sales",
                    datasource_id=1,
                ),
                Candidate(
                    doc_id="vq:2",
                    object_type="verified_query",
                    score=0.8,
                    source=CandidateSource.BM25,
                    domain="inventory",
                    datasource_id=1,
                ),
            ]
        )
        result = await repo.search_verified_queries("销售额", allowed_domains=["sales"])
        assert len(result.candidates) == 1
        assert result.candidates[0].doc_id == "vq:1"

    async def test_search_verified_queries_empty_domain_returns_all(self) -> None:
        repo = InMemorySearchRepository()
        repo.register_verified_query_candidates(
            [
                Candidate(
                    doc_id="vq:1",
                    object_type="verified_query",
                    score=0.9,
                    source=CandidateSource.BM25,
                    domain="sales",
                    datasource_id=1,
                ),
                Candidate(
                    doc_id="vq:2",
                    object_type="verified_query",
                    score=0.8,
                    source=CandidateSource.BM25,
                    domain="inventory",
                    datasource_id=1,
                ),
            ]
        )
        result = await repo.search_verified_queries("test", allowed_domains=[])
        assert len(result.candidates) == 2

    async def test_search_verified_queries_sorted_by_score(self) -> None:
        repo = InMemorySearchRepository()
        repo.register_verified_query_candidates(
            [
                Candidate(
                    doc_id="vq:low",
                    object_type="verified_query",
                    score=0.3,
                    source=CandidateSource.BM25,
                    domain="sales",
                    datasource_id=1,
                ),
                Candidate(
                    doc_id="vq:high",
                    object_type="verified_query",
                    score=0.95,
                    source=CandidateSource.BM25,
                    domain="sales",
                    datasource_id=1,
                ),
            ]
        )
        result = await repo.search_verified_queries("test", allowed_domains=["sales"])
        assert result.candidates[0].doc_id == "vq:high"


class TestBGERerankerEmptyCandidates:
    def test_bge_reranker_empty_input_returns_empty(self) -> None:
        """BGEReranker.rerank() 的 empty candidates 早返回路径。"""
        # 用 mock 模拟 FlagEmbedding 已安装的场景
        import sys
        from unittest.mock import MagicMock, patch

        mock_flag = MagicMock()
        mock_flag.FlagReranker = MagicMock(return_value=MagicMock())

        with patch.dict(sys.modules, {"FlagEmbedding": mock_flag}):
            from importlib import reload

            import server.search.reranker as reranker_mod

            reload(reranker_mod)
            bge = reranker_mod.BGEReranker.__new__(reranker_mod.BGEReranker)
            bge._model = MagicMock()
            result = bge.rerank("test", [], top_n=5)
            assert result == []

    def test_bge_reranker_rerank_with_candidates(self) -> None:
        """BGEReranker.rerank() 的正常调用路径（mock compute_score）。"""
        import sys
        from unittest.mock import MagicMock, patch

        mock_flag = MagicMock()
        mock_flag.FlagReranker = MagicMock(return_value=MagicMock())

        with patch.dict(sys.modules, {"FlagEmbedding": mock_flag}):
            from importlib import reload

            import server.search.reranker as reranker_mod

            reload(reranker_mod)

            mock_model = MagicMock()
            mock_model.compute_score.return_value = [0.9, 0.5]

            bge = reranker_mod.BGEReranker.__new__(reranker_mod.BGEReranker)
            bge._model = mock_model

            cands = [
                Candidate(
                    doc_id="table:1:pub:a",
                    object_type="table",
                    score=0.7,
                    source=CandidateSource.RRF,
                    domain="sales",
                    datasource_id=1,
                ),
                Candidate(
                    doc_id="table:1:pub:b",
                    object_type="table",
                    score=0.6,
                    source=CandidateSource.RRF,
                    domain="sales",
                    datasource_id=1,
                ),
            ]
            result = bge.rerank("test", cands, top_n=5)
            # a 得分 0.9 > b 得分 0.5，a 应排第一
            assert result[0].doc_id == "table:1:pub:a"
            assert result[0].score == 0.9

    async def test_inspect_with_injected_retriever(self) -> None:
        """注入 retriever / linker / join_graph 时，相关分支被覆盖。"""
        import httpx
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import FastAPI

        from server.api.retrieval_workbench import router
        from server.linking.join_graph import JoinGraphResult
        from server.linking.schema import LinkType, SchemaLink, SchemaLinkResult
        from server.search.repository import Candidate, CandidateSource
        from server.search.retrieval import SchemaContext

        fake_table = Candidate(
            doc_id="table:1:pub:fact_order",
            object_type="table",
            score=0.9,
            source=CandidateSource.RRF,
            domain="sales",
            datasource_id=1,
            payload={"table_name": "fact_order", "business_name": "订单事实表"},
        )
        fake_col = Candidate(
            doc_id="column:1:pub:fact_order:net_amount",
            object_type="column",
            score=0.8,
            source=CandidateSource.RRF,
            domain="sales",
            datasource_id=1,
            payload={"table_name": "fact_order", "column_name": "net_amount"},
        )
        fake_ctx = SchemaContext(tables=[fake_table], columns=[fake_col])

        fake_retriever = MagicMock()
        fake_retriever.retrieve = AsyncMock(return_value=fake_ctx)

        fake_linker = MagicMock()
        fake_linker.link.return_value = SchemaLinkResult(
            links=[
                SchemaLink(
                    source_text="销售额",
                    link_type=LinkType.METRIC,
                    target_id="metric:net_sales",
                    target_label="net_sales",
                    confidence=0.95,
                    evidence="alias",
                )
            ]
        )

        fake_join_graph = MagicMock()
        fake_join_graph.complete_schema.return_value = JoinGraphResult(
            complete_tables=["fact_order"],
            paths={},
            pre_aggregation_required=[],
            missing_paths=[],
        )

        app = FastAPI()
        app.include_router(router)
        app.state.two_level_retriever = fake_retriever
        app.state.schema_linker = fake_linker
        app.state.join_graph = fake_join_graph

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/admin/retrieval/inspect",
                json={"question": "今年销售额"},
            )
        assert response.status_code == 200
        body = response.json()
        assert len(body["reranked_tables"]) == 1
        assert body["reranked_tables"][0]["table_name"] == "fact_order"
        assert len(body["schema_links"]) == 1
        assert body["schema_links"][0]["source_text"] == "销售额"
        assert body["join_path"] is not None
        assert "fact_order" in body["join_path"]["complete_tables"]
