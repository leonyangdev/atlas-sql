"""Milvus collection schema 定义。

Collection 命名规则：``atlas_{env}_{object_type}``，与 OpenSearch 索引对齐。

Milvus schema 设计原则：
- ``doc_id``（varchar，主键）：与 OpenSearch 文档 ID 一致，支持跨存储 join。
- ``vector``（float_vector）：存储 Embedding 向量；维度必须与 EmbeddingProvider 一致。
- ``object_type``、``domain``、``authorized_roles``：scalar 字段，支持混合检索过滤。
- ``metadata_version``：检索时用于检测 stale 向量，触发重建。
- 向量维度写入 collection schema 后不能更改；模型升级需要新建 collection 再切换。

V0 阶段 Milvus 通过 TCP 握手验证连通性（见 health.py），不引入完整 SDK 依赖。
Collection 创建和向量写入在 V0-S05 的 tasks/index_build.py 中实现，
使用 pymilvus 的 grpc 接口。
"""

from typing import Any

# BGE-M3 的向量维度为 1024；如果切换到其他模型需要同时更新此常量和 collection schema
BGE_M3_DIMENSION = 1024

# HNSW 索引参数：M（每节点最大边数）和 ef_construction（建索引时的搜索宽度）
# 这两个参数影响索引质量和构建速度，生产调优时再修改
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 200


def schema_collection_schema(dimension: int = BGE_M3_DIMENSION) -> dict[str, Any]:
    """表和列的 Milvus collection schema。

    使用 HNSW 向量索引 + 内积（IP）度量，适合归一化的 BGE 向量。
    doc_id 作为 varchar 主键，与 OpenSearch 文档 ID 完全对应。
    """
    return {
        "collection_name": "{env}_schema",  # 调用方替换 {env}
        "description": "AtlasSQL schema embeddings for table and column retrieval",
        "fields": [
            {
                "name": "doc_id",
                "dtype": "VarChar",
                "is_primary": True,
                "max_length": 512,
                "description": "Stable document ID, matches OpenSearch _id",
            },
            {
                "name": "vector",
                "dtype": "FloatVector",
                "dim": dimension,
                "description": "Embedding vector from EmbeddingProvider",
            },
            {
                "name": "object_type",
                "dtype": "VarChar",
                "max_length": 32,
                "description": "table or column",
            },
            {
                "name": "domain",
                "dtype": "VarChar",
                "max_length": 64,
                "description": "Business domain for query routing",
            },
            {
                "name": "datasource_id",
                "dtype": "Int32",
                "description": "Source datasource ID",
            },
            {
                "name": "metadata_version",
                "dtype": "VarChar",
                "max_length": 64,
                "description": "Control plane schema version when indexed",
            },
            {
                "name": "embedding_model_version",
                "dtype": "VarChar",
                "max_length": 128,
                "description": "Model ID used to generate the vector",
            },
        ],
        "index_params": {
            "field_name": "vector",
            "index_type": "HNSW",
            "metric_type": "IP",
            "params": {
                "M": HNSW_M,
                "efConstruction": HNSW_EF_CONSTRUCTION,
            },
        },
    }


def verified_queries_collection_schema(dimension: int = BGE_M3_DIMENSION) -> dict[str, Any]:
    """已验证查询的 Milvus collection schema。"""
    return {
        "collection_name": "{env}_verified_queries",
        "description": "AtlasSQL verified query embeddings for few-shot retrieval",
        "fields": [
            {
                "name": "doc_id",
                "dtype": "VarChar",
                "is_primary": True,
                "max_length": 512,
            },
            {
                "name": "vector",
                "dtype": "FloatVector",
                "dim": dimension,
            },
            {
                "name": "domain",
                "dtype": "VarChar",
                "max_length": 64,
            },
            {
                "name": "difficulty",
                "dtype": "VarChar",
                "max_length": 32,
            },
            {
                "name": "metadata_version",
                "dtype": "VarChar",
                "max_length": 64,
            },
            {
                "name": "embedding_model_version",
                "dtype": "VarChar",
                "max_length": 128,
            },
        ],
        "index_params": {
            "field_name": "vector",
            "index_type": "HNSW",
            "metric_type": "IP",
            "params": {
                "M": HNSW_M,
                "efConstruction": HNSW_EF_CONSTRUCTION,
            },
        },
    }


def collection_name(env: str, object_type: str) -> str:
    """生成 Milvus collection 名称。

    示例：``collection_name("dev", "schema")`` → ``"atlas_dev_schema"``
    """
    return f"atlas_{env}_{object_type}"


# 预定义 collection 类型常量
COLLECTION_TYPE_SCHEMA = "schema"
COLLECTION_TYPE_VERIFIED_QUERIES = "verified_queries"
