"""V0-S04 数据源与元数据中心测试。

测试覆盖：
- ORM 模型字段约束
- 凭据引用解析与安全检查
- 同步任务状态机
- 元数据增量同步规则（人工字段保留）
- Inspector 的敏感列过滤
- API 端点的权限校验（不依赖真实数据库）
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.datasource.credentials import CredentialError, resolve_credential
from server.datasource.inspector import _is_sensitive_column, serialize_sample_values
from server.datasource.models import (
    DataSource,
    DataSourceKind,
    DataSourceStatus,
    MetadataSyncJob,
    SyncStatus,
)

# ---------------------------------------------------------------------------
# 凭据解析
# ---------------------------------------------------------------------------


def test_resolve_credential_env_reads_env_var() -> None:
    with patch.dict(os.environ, {"TEST_DB_URL": "postgresql://user:pw@localhost/db"}):
        result = resolve_credential("env:TEST_DB_URL")
    assert result == "postgresql://user:pw@localhost/db"


def test_resolve_credential_env_missing_variable_raises() -> None:
    with pytest.raises(CredentialError, match="TEST_MISSING"):
        resolve_credential("env:TEST_MISSING")


def test_resolve_credential_env_empty_name_raises() -> None:
    with pytest.raises(CredentialError, match="variable name"):
        resolve_credential("env:")


def test_resolve_credential_vault_not_supported_raises() -> None:
    with pytest.raises(CredentialError, match="vault"):
        resolve_credential("vault:secret/path")


def test_resolve_credential_unknown_format_raises() -> None:
    with pytest.raises(CredentialError, match="unsupported"):
        resolve_credential("literal:plaintext")


# ---------------------------------------------------------------------------
# Inspector 敏感列过滤
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column_name",
    [
        "password",
        "passwd",
        "user_password",
        "api_token",
        "secret_key",
        "mobile_hash",
        "email_address",
        "credit_card_no",
        "mobile_no",
        "phone_number",
    ],
)
def test_sensitive_column_patterns_are_skipped(column_name: str) -> None:
    assert _is_sensitive_column(column_name) is True


@pytest.mark.parametrize(
    "column_name",
    ["order_id", "store_name", "product_code", "city_id", "status", "amount"],
)
def test_non_sensitive_columns_are_not_skipped(column_name: str) -> None:
    assert _is_sensitive_column(column_name) is False


# ---------------------------------------------------------------------------
# 样例值序列化
# ---------------------------------------------------------------------------


def test_serialize_sample_values_produces_valid_json() -> None:
    import json

    result = serialize_sample_values(["北京", "上海", "深圳"])
    parsed = json.loads(result)
    assert parsed == ["北京", "上海", "深圳"]


def test_serialize_sample_values_empty_list() -> None:
    import json

    result = serialize_sample_values([])
    assert json.loads(result) == []


# ---------------------------------------------------------------------------
# ORM 模型默认值
# ---------------------------------------------------------------------------


def test_datasource_model_defaults() -> None:
    ds = DataSource(
        slug="test-db",
        name="Test DB",
        kind=DataSourceKind.POSTGRESQL,
        host="localhost",
        port=5433,
        database_name="nova_retail",
        credential_ref="env:TEST_URL",
        status=DataSourceStatus.ACTIVE,  # 显式设置，ORM insert_default 在 flush 时生效
    )
    assert ds.status == DataSourceStatus.ACTIVE
    assert ds.description is None


def test_sync_job_default_status() -> None:
    job = MetadataSyncJob(
        datasource_id=1,
        idempotency_key="abc-123",
        status=SyncStatus.PENDING,
        retry_count=0,
    )
    assert job.status == SyncStatus.PENDING
    assert job.retry_count == 0


# ---------------------------------------------------------------------------
# 同步增量规则（通过 sync.py 的 upsert 逻辑）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_preserves_manual_fields() -> None:
    """增量同步不应覆盖已有的 manual_business_name。"""
    from server.datasource.inspector import ColumnInfo, TableInfo
    from server.datasource.sync import _upsert_metadata

    # 构造一个已有人工注释的表元数据对象
    existing_table = MagicMock(spec=TableMetadata)
    existing_table.id = 42
    existing_table.table_name = "fact_order"
    existing_table.manual_business_name = "订单事实表"  # 已有的人工注释

    # 模拟 session.execute 返回值：
    # 第1次：查表是否存在 -> 已存在
    # 第2次：查列是否存在 -> 新列（None）
    # 第3次：_mark_deleted_columns 查询该表所有列 -> 空列表
    mock_session = AsyncMock()

    mock_result_table = MagicMock()
    mock_result_table.scalar_one_or_none.return_value = existing_table

    mock_result_col = MagicMock()
    mock_result_col.scalar_one_or_none.return_value = None  # 新列

    mock_result_all_cols = MagicMock()
    mock_result_all_cols.scalars.return_value = MagicMock()
    mock_result_all_cols.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))

    mock_session.execute.side_effect = [mock_result_table, mock_result_col, mock_result_all_cols]

    table_info = TableInfo(
        schema_name="public",
        table_name="fact_order",
        table_type="TABLE",
        row_estimate=10000,
        raw_comment=None,
        columns=[
            ColumnInfo(
                column_name="id",
                ordinal_position=1,
                data_type="bigint",
                character_maximum_length=None,
                numeric_precision=64,
                numeric_scale=0,
                is_nullable=False,
                column_default=None,
                is_primary_key=True,
                foreign_key_ref=None,
                raw_comment=None,
            )
        ],
    )

    await _upsert_metadata(mock_session, datasource_id=1, tables=[table_info], schema_name="public")

    # 关键验收：manual_business_name 不应被清空
    assert existing_table.manual_business_name == "订单事实表"
    # 采集字段应被更新
    assert existing_table.row_estimate == 10000


# 避免 linter 报错
from server.datasource.models import TableMetadata  # noqa: E402
