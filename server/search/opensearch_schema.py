"""OpenSearch 索引 mapping 定义。

每类对象一个独立索引，避免 field type 冲突和跨类型查询的混淆。

索引命名规则：``atlas_{env}_{object_type}``，例如：
- ``atlas_dev_schema``    — 表和列的词法检索索引
- ``atlas_dev_metrics``   — 指标索引
- ``atlas_dev_verified_queries`` — 已验证查询索引

Mapping 设计原则：
- ``doc_id``：keyword，用于幂等 upsert 和交叉比对。
- ``object_type``：keyword，方便过滤。
- ``domain``：keyword，支持按业务域路由查询范围。
- ``authorized_roles``：keyword 数组，V4 权限层在检索时过滤。
- ``metadata_version``：keyword，记录产生该文档的控制库 schema 版本，版本不匹配时重建。
- 业务文本字段统一使用 ``text`` + ``ik_max_word``（中文分词），英文字段使用 standard。
- 数值和日期字段避免 text 映射，防止全文扫描。
"""

from typing import Any


def schema_index_mapping() -> dict[str, Any]:
    """表和列的 OpenSearch mapping。

    表级字段：table_name、business_name、description、domain、grain、aliases、synonyms。
    列级字段：column_name、business_name、description、data_type、sample_values、aliases。

    每个文档都包含所属表的摘要（table_name、domain），使列级结果可以独立理解。
    """
    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    # 中英文混合分析器：先 ik_max_word 做中文最大颗粒度切分，再 lowercase
                    "atlas_text": {
                        "type": "custom",
                        "tokenizer": "ik_max_word",
                        "filter": ["lowercase"],
                    },
                    # 纯英文，适合列名/代码
                    "atlas_identifier": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "word_delimiter_graph"],
                    },
                }
            },
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                # ---- 稳定标识符 ----
                "doc_id": {"type": "keyword"},
                "object_type": {"type": "keyword"},  # "table" or "column"
                # ---- 来源追踪 ----
                "datasource_id": {"type": "integer"},
                "schema_name": {"type": "keyword"},
                "table_name": {"type": "keyword"},
                "column_name": {"type": "keyword"},  # 表文档为 null
                # ---- 业务域路由 ----
                "domain": {"type": "keyword"},
                # ---- 授权标签（V4 过滤用）----
                "authorized_roles": {"type": "keyword"},
                # ---- 版本追踪 ----
                "metadata_version": {"type": "keyword"},
                "embedding_model_version": {"type": "keyword"},
                # ---- 全文检索字段 ----
                "business_name": {
                    "type": "text",
                    "analyzer": "atlas_text",
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                },
                "description": {"type": "text", "analyzer": "atlas_text"},
                "aliases": {
                    "type": "text",
                    "analyzer": "atlas_text",
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                },
                # 物理名：字段名 / 表名（用于编码精确匹配）
                "physical_name": {
                    "type": "text",
                    "analyzer": "atlas_identifier",
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                },
                # ---- 列专用字段 ----
                "data_type": {"type": "keyword"},
                "sample_values": {"type": "text", "analyzer": "atlas_text"},
                # ---- 表专用字段 ----
                "grain": {"type": "text", "analyzer": "atlas_text"},
                "table_type": {"type": "keyword"},  # TABLE / VIEW
                "row_estimate": {"type": "long"},
                # ---- 时间戳 ----
                "indexed_at": {"type": "date"},
            },
        },
    }


def metrics_index_mapping() -> dict[str, Any]:
    """指标的 OpenSearch mapping。"""
    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "doc_id": {"type": "keyword"},
                "object_type": {"type": "keyword"},
                "metric_id": {"type": "keyword"},
                "domain": {"type": "keyword"},
                "authorized_roles": {"type": "keyword"},
                "metadata_version": {"type": "keyword"},
                "label": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                },
                "description": {"type": "text"},
                "synonyms": {"type": "text"},
                "expression": {"type": "keyword"},
                "indexed_at": {"type": "date"},
            },
        },
    }


def verified_queries_index_mapping() -> dict[str, Any]:
    """已验证查询的 OpenSearch mapping。"""
    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "doc_id": {"type": "keyword"},
                "object_type": {"type": "keyword"},
                "query_id": {"type": "integer"},
                "domain": {"type": "keyword"},
                "authorized_roles": {"type": "keyword"},
                "metadata_version": {"type": "keyword"},
                "question": {"type": "text"},
                "sql_text": {"type": "text"},
                "tags": {"type": "keyword"},
                "difficulty": {"type": "keyword"},
                "indexed_at": {"type": "date"},
            },
        },
    }


def index_name(env: str, object_type: str) -> str:
    """生成带环境前缀的索引名称。

    例如：``index_name("dev", "schema")`` → ``"atlas_dev_schema"``
    """
    return f"atlas_{env}_{object_type}"


# 预定义的索引类型常量，避免硬编码字符串分散在代码各处
INDEX_TYPE_SCHEMA = "schema"
INDEX_TYPE_METRICS = "metrics"
INDEX_TYPE_VERIFIED_QUERIES = "verified_queries"
