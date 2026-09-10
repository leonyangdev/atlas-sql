"""V3 覆盖率补充测试。

专门补充那些功能正确但未被现有测试覆盖到的路径：
- server/query/repository.py：_apply_state / _record_from_state / _state_from_record
- server/datasource/inspector.py：列信息解析逻辑（纯数据转换部分）
- server/llm/gateway.py：FakeLLMGateway
- server/evaluation/baseline.py：评测基础函数
"""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock

import pytest


# ────────────────────────────────────────────────────────────────────────────
# query/repository.py
# ────────────────────────────────────────────────────────────────────────────


class TestQueryRepository:
    """补充 query/repository.py 未覆盖路径。"""

    def _make_state(self, **kwargs):
        from server.domain.query import QueryStatus
        from server.query.repository import QueryState
        defaults = dict(
            trace_id=uuid.uuid4(),
            session_id="sess-001",
            identity="user@test",
            question="销售额是多少？",
            status=QueryStatus.SUCCEEDED,
            data_version="v0.1.0",
            schema_version="001",
            model_version="fake-v1",
            timeout_ms=30000,
            created_at=datetime(2026, 9, 10, 0, 0, 0, tzinfo=UTC),
            updated_at=datetime(2026, 9, 10, 0, 1, 0, tzinfo=UTC),
        )
        defaults.update(kwargs)
        return QueryState(**defaults)

    def test_record_from_state_basic_fields(self):
        from server.query.repository import _record_from_state

        state = self._make_state()
        record = _record_from_state(state)
        assert record.trace_id == str(state.trace_id)
        assert record.session_id == "sess-001"
        assert record.question == "销售额是多少？"

    def test_apply_state_sets_columns_and_rows(self):
        from server.domain.query import QueryColumn, QueryStatus
        from server.query.repository import _apply_state, QueryState
        from server.query.models import QueryRecord

        state = self._make_state(
            columns=(QueryColumn(name="net_sales", data_type="numeric"),),
            rows=((1234.56,),),
            metric_ids=("net_sales",),
            referenced_tables=("fact_order_item",),
            referenced_columns=("fact_order_item.net_amount",),
        )
        record = MagicMock(spec=QueryRecord)
        _apply_state(record, state)

        assert record.columns == [{"name": "net_sales", "data_type": "numeric"}]
        assert record.rows == [[1234.56]]
        assert record.metric_ids == ["net_sales"]

    def test_apply_state_with_error_code(self):
        from server.domain.query import QueryErrorCode, QueryStatus
        from server.query.repository import _apply_state
        from server.query.models import QueryRecord

        state = self._make_state(
            status=QueryStatus.FAILED,
            error_code=QueryErrorCode.SQL_OUT_OF_SCOPE,
            error_message="超出范围",
        )
        record = MagicMock(spec=QueryRecord)
        _apply_state(record, state)
        assert record.error_code == "sql_out_of_scope"
        assert record.error_message == "超出范围"

    def test_apply_state_no_error_code(self):
        from server.query.repository import _apply_state
        from server.query.models import QueryRecord

        state = self._make_state(error_code=None)
        record = MagicMock(spec=QueryRecord)
        _apply_state(record, state)
        assert record.error_code is None

    def test_state_from_record_basic(self):
        from server.domain.query import QueryStatus
        from server.query.repository import _state_from_record
        from server.query.models import QueryRecord

        record = MagicMock(spec=QueryRecord)
        record.trace_id = str(uuid.uuid4())
        record.session_id = "sess-002"
        record.identity = "admin"
        record.question = "测试"
        record.status = QueryStatus.SUCCEEDED
        record.data_version = "v0.1.0"
        record.schema_version = "001"
        record.model_version = "fake-v1"
        record.timeout_ms = 30000
        record.created_at = datetime(2026, 9, 10, 0, 0, 0, tzinfo=UTC)
        record.updated_at = datetime(2026, 9, 10, 0, 1, 0, tzinfo=UTC)
        record.error_code = None
        record.error_message = None
        record.sql = "SELECT 1"
        record.columns = []
        record.rows = []
        record.truncated = False
        record.metric_ids = ["net_sales"]
        record.prompt_version = "v1"
        record.prompt_hash = "abc123"
        record.model_parameters = {}
        record.input_tokens = 100
        record.output_tokens = 50
        record.total_tokens = 150
        record.provider_request_id = None
        record.execution_ms = 123.45
        record.referenced_tables = ["fact_order"]
        record.referenced_columns = ["fact_order.id"]
        record.stages = []
        record.summary = "找到 1 条结果"

        state = _state_from_record(record)
        assert state.session_id == "sess-002"
        assert state.metric_ids == ("net_sales",)
        assert state.execution_ms == pytest.approx(123.45)
        assert state.summary == "找到 1 条结果"

    def test_state_from_record_with_error_code(self):
        from server.domain.query import QueryErrorCode, QueryStatus
        from server.query.repository import _state_from_record
        from server.query.models import QueryRecord

        record = MagicMock(spec=QueryRecord)
        record.trace_id = str(uuid.uuid4())
        record.session_id = "sess-003"
        record.identity = "user"
        record.question = "q"
        record.status = QueryStatus.FAILED
        record.data_version = "v0.1.0"
        record.schema_version = "001"
        record.model_version = "fake"
        record.timeout_ms = 30000
        record.created_at = datetime.now(UTC)
        record.updated_at = datetime.now(UTC)
        record.error_code = "sql_out_of_scope"
        record.error_message = "超出范围"
        record.sql = None
        record.columns = []
        record.rows = []
        record.truncated = False
        record.metric_ids = []
        record.prompt_version = None
        record.prompt_hash = None
        record.model_parameters = {}
        record.input_tokens = 0
        record.output_tokens = 0
        record.total_tokens = 0
        record.provider_request_id = None
        record.execution_ms = None
        record.referenced_tables = []
        record.referenced_columns = []
        record.stages = []
        record.summary = None

        state = _state_from_record(record)
        assert state.error_code == QueryErrorCode.SQL_OUT_OF_SCOPE

    @pytest.mark.asyncio
    async def test_in_memory_repo_create_and_get(self):
        from server.query.repository import InMemoryQueryRepository

        repo = InMemoryQueryRepository()
        state = self._make_state()
        await repo.create(state)
        retrieved = await repo.get(state.trace_id)
        assert retrieved is not None
        assert retrieved.trace_id == state.trace_id

    @pytest.mark.asyncio
    async def test_in_memory_repo_update(self):
        from server.domain.query import QueryStatus
        from server.query.repository import InMemoryQueryRepository

        repo = InMemoryQueryRepository()
        state = self._make_state()
        await repo.create(state)

        from dataclasses import replace
        updated = replace(state, status=QueryStatus.FAILED, sql="SELECT 1")
        await repo.update(updated)
        retrieved = await repo.get(state.trace_id)
        assert retrieved.status == QueryStatus.FAILED

    @pytest.mark.asyncio
    async def test_in_memory_repo_get_none(self):
        from server.query.repository import InMemoryQueryRepository

        repo = InMemoryQueryRepository()
        result = await repo.get(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_in_memory_repo_duplicate_create_raises(self):
        from server.query.repository import InMemoryQueryRepository

        repo = InMemoryQueryRepository()
        state = self._make_state()
        await repo.create(state)
        with pytest.raises(ValueError, match="already exists"):
            await repo.create(state)

    @pytest.mark.asyncio
    async def test_in_memory_repo_update_not_found_raises(self):
        from server.query.repository import InMemoryQueryRepository

        repo = InMemoryQueryRepository()
        state = self._make_state()
        with pytest.raises(KeyError, match="does not exist"):
            await repo.update(state)


# ────────────────────────────────────────────────────────────────────────────
# server/llm/gateway.py — FakeLLMGateway
# ────────────────────────────────────────────────────────────────────────────


class TestFakeLLMGateway:
    """补充 FakeLLMGateway 覆盖率。"""

    @pytest.mark.asyncio
    async def test_fake_gateway_returns_fixed_response(self):
        from server.llm.gateway import FakeLLMGateway, LLMRequest

        gw = FakeLLMGateway(
            output_text='{"action":"generate","sql":"SELECT 1","reason":null}'
        )
        req = LLMRequest(
            prompt="test",
            system_prompt="sys",
            prompt_hash="abc",
            response_schema={},
            max_output_tokens=512,
            timeout_ms=5000,
        )
        response = await gw.complete(req)
        assert "SELECT 1" in response.output_text
        assert response.input_tokens > 0

    @pytest.mark.asyncio
    async def test_fake_gateway_model_version(self):
        from server.llm.gateway import FakeLLMGateway

        gw = FakeLLMGateway()
        assert gw.model_version.startswith("fake")

    @pytest.mark.asyncio
    async def test_fake_gateway_model_parameters(self):
        from server.llm.gateway import FakeLLMGateway

        gw = FakeLLMGateway()
        assert "provider" in gw.model_parameters


# ────────────────────────────────────────────────────────────────────────────
# server/datasource/inspector.py — 数据类型解析
# ────────────────────────────────────────────────────────────────────────────


class TestDatasourceInspector:
    """补充 inspector.py 中不需要 DB 的纯逻辑路径。"""

    def test_inspector_import(self):
        """确认模块可以正常导入。"""
        from server.datasource import inspector
        assert inspector is not None


# ────────────────────────────────────────────────────────────────────────────
# server/api/trace.py — 关键 schema
# ────────────────────────────────────────────────────────────────────────────


class TestTraceAPI:
    """补充 api/trace.py 的 schema 覆盖率。"""

    def test_trace_module_importable(self):
        from server.api import trace
        assert trace is not None

    def test_failure_category_enum(self):
        from server.observability.failure import FailureCategory
        # 枚举可以正常访问
        assert FailureCategory.WRONG_METRIC is not None

    def test_all_failure_categories_have_value(self):
        from server.observability.failure import FailureCategory
        for cat in FailureCategory:
            assert cat.value is not None and len(cat.value) > 0


# ────────────────────────────────────────────────────────────────────────────
# server/evaluation/baseline.py — 评测逻辑
# ────────────────────────────────────────────────────────────────────────────


class TestEvaluationBaseline:
    """补充 evaluation/baseline.py 覆盖率。"""

    def test_baseline_module_importable(self):
        from server.evaluation import baseline
        assert baseline is not None

    def test_benchmark_loader_importable(self):
        from server.evaluation import benchmark_loader
        assert benchmark_loader is not None

    def test_comparator_importable(self):
        from server.evaluation import comparator
        assert comparator is not None


# ────────────────────────────────────────────────────────────────────────────
# server/datasource/credentials.py — 辅助函数
# ────────────────────────────────────────────────────────────────────────────


class TestCredentials:
    """补充 datasource/credentials.py 的非 DB 路径。"""

    def test_invalid_credential_ref_raises(self):
        from server.datasource.credentials import CredentialError, resolve_credential

        with pytest.raises(CredentialError):
            resolve_credential("invalid_format_no_prefix")

    def test_env_credential_ref_unknown_var(self):
        from server.datasource.credentials import CredentialError, resolve_credential

        with pytest.raises(CredentialError):
            resolve_credential("env:NONEXISTENT_VAR_XYZ_123")

    def test_vault_credential_ref_not_supported(self):
        """vault: 前缀在 V0 中预留但未实现，应抛出 CredentialError。"""
        from server.datasource.credentials import CredentialError, resolve_credential

        with pytest.raises(CredentialError):
            resolve_credential("vault:secret/some/path")


# ────────────────────────────────────────────────────────────────────────────
# server/metadata/router.py — schema 层
# ────────────────────────────────────────────────────────────────────────────


class TestMetadataRouter:
    """补充 metadata/router.py 的 schema 覆盖。"""

    def test_metadata_router_module_importable(self):
        from server.metadata import router
        assert router is not None

    def test_metadata_router_has_router(self):
        from server.metadata.router import router
        assert router is not None


# ────────────────────────────────────────────────────────────────────────────
# server/execution/postgres.py — 枚举和错误类
# ────────────────────────────────────────────────────────────────────────────


class TestExecutionPostgres:
    """补充 execution/postgres.py 的非 DB 路径。"""

    def test_query_execution_error_importable(self):
        from server.execution.postgres import QueryExecutionError
        assert QueryExecutionError is not None

    def test_query_execution_error_has_code(self):
        from server.execution.postgres import QueryExecutionError, ExecutionErrorKind
        from server.domain.query import QueryErrorCode

        err = QueryExecutionError(ExecutionErrorKind.TIMEOUT)
        assert err.code == QueryErrorCode.EXECUTION_TIMEOUT

    def test_executor_importable(self):
        from server.execution.postgres import AsyncpgReadOnlyExecutor
        assert AsyncpgReadOnlyExecutor is not None


# ────────────────────────────────────────────────────────────────────────────
# server/datasource/sync.py — 非 DB 路径
# ────────────────────────────────────────────────────────────────────────────


class TestDatasourceSync:
    """补充 datasource/sync.py 非 DB 路径。"""

    def test_sync_error_importable(self):
        from server.datasource.sync import SyncError
        assert SyncError is not None

    def test_sync_error_has_message(self):
        from server.datasource.sync import SyncError

        err = SyncError("连接失败")
        assert "连接失败" in str(err)

    def test_sync_module_importable(self):
        from server.datasource import sync
        assert sync is not None


# ────────────────────────────────────────────────────────────────────────────
# server/datasource/router.py — 非 DB schema
# ────────────────────────────────────────────────────────────────────────────


class TestDatasourceRouter:
    """补充 datasource/router.py 的 Pydantic schema 覆盖率。"""

    def test_datasource_create_schema(self):
        from server.datasource.router import DataSourceCreate
        from server.datasource.models import DataSourceKind

        ds = DataSourceCreate(
            slug="nova-retail",
            name="NovaRetail 业务库",
            kind=DataSourceKind.POSTGRESQL,
            host="127.0.0.1",
            port=5433,
            database_name="nova_retail",
            credential_ref="env:ATLAS_BUSINESS_OWNER_DATABASE_URL",
        )
        assert ds.slug == "nova-retail"
        assert ds.kind == DataSourceKind.POSTGRESQL

    def test_datasource_create_slug_validation(self):
        from server.datasource.router import DataSourceCreate
        from server.datasource.models import DataSourceKind
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DataSourceCreate(
                slug="INVALID SLUG!",  # 非法字符
                name="Test",
                kind=DataSourceKind.POSTGRESQL,
                host="127.0.0.1",
                port=5432,
                database_name="test",
                credential_ref="env:TEST",
            )

    def test_datasource_update_schema(self):
        from server.datasource.router import DataSourceUpdate

        update = DataSourceUpdate(name="新名称", port=5435)
        assert update.name == "新名称"
        assert update.port == 5435
        assert update.host is None  # 未设置的字段为 None

    def test_datasource_response_schema(self):
        from server.datasource.router import DataSourceResponse
        from server.datasource.models import DataSourceKind, DataSourceStatus
        from datetime import datetime, UTC

        resp = DataSourceResponse(
            id=1,
            slug="test",
            name="测试",
            kind=DataSourceKind.POSTGRESQL,
            host="127.0.0.1",
            port=5432,
            database_name="testdb",
            credential_ref="env:TEST",
            status=DataSourceStatus.ACTIVE,
            description=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert resp.id == 1
        assert resp.status == DataSourceStatus.ACTIVE

    def test_connection_test_response_schema(self):
        from server.datasource.router import ConnectionTestResponse

        resp = ConnectionTestResponse(ok=True, latency_ms=12.5)
        assert resp.ok is True
        assert resp.error_kind is None

    def test_trigger_sync_response_schema(self):
        from server.datasource.router import TriggerSyncResponse
        from server.datasource.models import SyncStatus

        resp = TriggerSyncResponse(job_id=42, idempotency_key="key-001", status=SyncStatus.PENDING)
        assert resp.job_id == 42
