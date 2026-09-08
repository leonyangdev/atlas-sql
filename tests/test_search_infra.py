"""V0-S05 索引基础设施测试。

覆盖：
- 文档 ID 稳定性（相同对象 ID 不变）
- Milvus collection schema 维度约束
- OpenSearch mapping 字段完整性
- EmbeddingProvider 协议（FakeProvider 验证形状）
- Redis 缓存键命名规则
- 缓存 TTL 分级合理性
"""

import json

import pytest

from server.llm.embedding import EmbeddingProvider, FakeEmbeddingProvider
from server.search.cache import (
    CacheTTL,
    SchemaCache,
    hash_sql,
    make_schema_key,
    make_schema_prefix,
)
from server.search.document_id import (
    doc_id_to_milvus_pk,
    make_column_doc_id,
    make_metric_doc_id,
    make_table_doc_id,
    make_verified_query_doc_id,
)
from server.search.milvus_schema import BGE_M3_DIMENSION, collection_name, schema_collection_schema
from server.search.opensearch_schema import index_name, schema_index_mapping

# ---------------------------------------------------------------------------
# 文档 ID 稳定性
# ---------------------------------------------------------------------------


def test_table_doc_id_is_stable() -> None:
    """相同参数生成的 doc_id 必须完全一致。"""
    id1 = make_table_doc_id(1, "public", "fact_order")
    id2 = make_table_doc_id(1, "public", "fact_order")
    assert id1 == id2 == "table:1:public:fact_order"


def test_column_doc_id_is_stable() -> None:
    id1 = make_column_doc_id(1, "public", "fact_order", "order_no")
    id2 = make_column_doc_id(1, "public", "fact_order", "order_no")
    assert id1 == id2 == "column:1:public:fact_order:order_no"


def test_doc_ids_are_unique_across_types() -> None:
    """表 ID 和列 ID 不能相同，避免在同一索引中碰撞。"""
    table_id = make_table_doc_id(1, "public", "fact_order")
    col_id = make_column_doc_id(1, "public", "fact_order", "id")
    assert table_id != col_id


def test_metric_doc_id() -> None:
    assert make_metric_doc_id("net_sales") == "metric:net_sales"


def test_verified_query_doc_id() -> None:
    assert make_verified_query_doc_id(42) == "verified_query:42"


def test_milvus_pk_short_id_unchanged() -> None:
    """短 doc_id 不做任何变换。"""
    doc_id = "table:1:public:fact_order"
    assert doc_id_to_milvus_pk(doc_id) == doc_id


def test_milvus_pk_long_id_is_shortened() -> None:
    """超过 255 字节的 doc_id 应被缩短为前缀 + 哈希。"""
    long_id = "column:1:public:" + "a" * 300
    pk = doc_id_to_milvus_pk(long_id)
    assert len(pk.encode()) <= 60  # 40 + 1 + 16
    assert "#" in pk  # 格式标志


# ---------------------------------------------------------------------------
# Milvus collection schema
# ---------------------------------------------------------------------------


def test_milvus_schema_has_correct_dimension() -> None:
    schema = schema_collection_schema(dimension=BGE_M3_DIMENSION)
    vector_field = next(f for f in schema["fields"] if f["name"] == "vector")
    assert vector_field["dim"] == BGE_M3_DIMENSION == 1024


def test_milvus_schema_has_primary_key() -> None:
    schema = schema_collection_schema()
    pk_fields = [f for f in schema["fields"] if f.get("is_primary")]
    assert len(pk_fields) == 1
    assert pk_fields[0]["name"] == "doc_id"


def test_milvus_schema_index_uses_inner_product() -> None:
    """BGE 向量使用内积（IP）度量，不是 L2。"""
    schema = schema_collection_schema()
    assert schema["index_params"]["metric_type"] == "IP"


def test_milvus_collection_name() -> None:
    assert collection_name("dev", "schema") == "atlas_dev_schema"
    assert collection_name("prod", "verified_queries") == "atlas_prod_verified_queries"


# ---------------------------------------------------------------------------
# OpenSearch mapping
# ---------------------------------------------------------------------------


def test_opensearch_mapping_has_doc_id_keyword() -> None:
    mapping = schema_index_mapping()
    props = mapping["mappings"]["properties"]
    assert props["doc_id"]["type"] == "keyword"


def test_opensearch_mapping_strict_dynamic() -> None:
    """strict 防止意外字段被自动映射，避免 mapping 爆炸。"""
    mapping = schema_index_mapping()
    assert mapping["mappings"]["dynamic"] == "strict"


def test_opensearch_mapping_has_all_required_fields() -> None:
    required = {
        "doc_id",
        "object_type",
        "datasource_id",
        "schema_name",
        "table_name",
        "column_name",
        "domain",
        "authorized_roles",
        "metadata_version",
        "business_name",
        "description",
        "physical_name",
        "indexed_at",
    }
    props = set(schema_index_mapping()["mappings"]["properties"].keys())
    assert required <= props


def test_opensearch_index_name() -> None:
    assert index_name("dev", "schema") == "atlas_dev_schema"
    assert index_name("prod", "metrics") == "atlas_prod_metrics"


# ---------------------------------------------------------------------------
# EmbeddingProvider（FakeProvider）
# ---------------------------------------------------------------------------


def test_fake_provider_satisfies_protocol() -> None:
    provider = FakeEmbeddingProvider(dimension=8)
    assert isinstance(provider, EmbeddingProvider)


def test_fake_provider_returns_correct_dimension() -> None:
    provider = FakeEmbeddingProvider(dimension=16)
    results = provider.embed_batch(["hello world"])
    assert len(results) == 1
    assert len(results[0].dense) == 16


def test_fake_provider_is_deterministic() -> None:
    provider = FakeEmbeddingProvider(dimension=8)
    r1 = provider.embed_batch(["北京"])
    r2 = provider.embed_batch(["北京"])
    assert r1[0].dense == r2[0].dense


def test_fake_provider_different_texts_produce_different_vectors() -> None:
    provider = FakeEmbeddingProvider(dimension=8)
    r1 = provider.embed_batch(["fact_order"])
    r2 = provider.embed_batch(["dim_customer"])
    assert r1[0].dense != r2[0].dense


def test_fake_provider_empty_input() -> None:
    provider = FakeEmbeddingProvider(dimension=8)
    results = provider.embed_batch([])
    assert results == []


def test_fake_provider_batch_length_matches_input() -> None:
    provider = FakeEmbeddingProvider(dimension=8)
    texts = ["a", "b", "c", "d"]
    results = provider.embed_batch(texts)
    assert len(results) == len(texts)


def test_fake_provider_model_version_contains_dimension() -> None:
    provider = FakeEmbeddingProvider(dimension=1024)
    assert "1024" in provider.model_version


# ---------------------------------------------------------------------------
# Redis 缓存键
# ---------------------------------------------------------------------------


def test_schema_key_includes_all_parts() -> None:
    key = make_schema_key("dev", 1, "v001", "fact_order")
    assert "dev" in key
    assert "1" in key
    assert "v001" in key
    assert "fact_order" in key


def test_schema_prefix_is_subset_of_schema_key() -> None:
    key = make_schema_key("dev", 1, "v001", "fact_order")
    prefix = make_schema_prefix("dev", 1)
    assert key.startswith(prefix)


def test_hash_sql_is_deterministic() -> None:
    sql = "SELECT * FROM fact_order WHERE id = 1"
    assert hash_sql(sql) == hash_sql(sql)


def test_hash_sql_normalizes_whitespace() -> None:
    """多余空格和换行不影响哈希结果。"""
    sql1 = "SELECT *  FROM  fact_order"
    sql2 = "SELECT * FROM fact_order"
    assert hash_sql(sql1) == hash_sql(sql2)


def test_hash_sql_different_sqls_produce_different_hashes() -> None:
    assert hash_sql("SELECT 1") != hash_sql("SELECT 2")


def test_cache_ttl_ordering() -> None:
    """Schema 缓存时间 > 指标缓存 > Session > 查询结果。"""
    assert CacheTTL.SCHEMA > CacheTTL.METRIC > CacheTTL.SESSION > CacheTTL.QUERY_RESULT


# ---------------------------------------------------------------------------
# SchemaCache（mock redis）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_cache_set_and_get() -> None:
    from unittest.mock import AsyncMock

    mock_redis = AsyncMock()
    table_data = {"table_name": "fact_order", "domain": "sales"}
    mock_redis.get.return_value = json.dumps(table_data).encode()

    cache = SchemaCache(mock_redis, env="dev")
    result = await cache.get_table(1, "v001", "fact_order")

    assert result == table_data
    mock_redis.get.assert_called_once()


@pytest.mark.asyncio
async def test_schema_cache_miss_returns_none() -> None:
    from unittest.mock import AsyncMock

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    cache = SchemaCache(mock_redis, env="dev")
    result = await cache.get_table(1, "v001", "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_schema_cache_invalidate_uses_scan() -> None:
    """失效操作使用 SCAN 而不是 KEYS。"""
    from unittest.mock import AsyncMock

    mock_redis = AsyncMock()
    # SCAN 返回 (cursor=0, keys=[])，表示只扫一轮
    mock_redis.scan.return_value = (0, [b"atlas:dev:1:v001:schema:table:fact_order"])
    mock_redis.delete.return_value = 1

    cache = SchemaCache(mock_redis, env="dev")
    deleted = await cache.invalidate_datasource(1)

    assert deleted == 1
    mock_redis.scan.assert_called_once()
