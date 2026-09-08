"""稳定文档 ID 生成规则。

索引文档 ID 必须满足：
1. **稳定**：相同对象重新索引时 ID 不变，确保 upsert 幂等而不是追加重复文档。
2. **可溯源**：能从 ID 反推对象类型和来源，便于调试和差异报告。
3. **跨存储一致**：OpenSearch 和 Milvus 使用同一 ID，方便交叉对比和重建。

ID 格式：``{object_type}:{datasource_id}:{schema}:{table}[:{column}]``

例如：
- 表文档：``table:1:public:fact_order``
- 列文档：``column:1:public:fact_order:order_no``
- 指标文档：``metric:net_sales``
- 验证查询：``verified_query:42``
"""

from hashlib import sha256


def make_table_doc_id(datasource_id: int, schema_name: str, table_name: str) -> str:
    """生成表级文档的稳定 ID。

    示例：``table:1:public:fact_order``
    """
    return f"table:{datasource_id}:{schema_name}:{table_name}"


def make_column_doc_id(
    datasource_id: int, schema_name: str, table_name: str, column_name: str
) -> str:
    """生成列级文档的稳定 ID。

    示例：``column:1:public:fact_order:order_no``
    """
    return f"column:{datasource_id}:{schema_name}:{table_name}:{column_name}"


def make_metric_doc_id(metric_id: str) -> str:
    """生成指标文档的稳定 ID。

    示例：``metric:net_sales``
    """
    return f"metric:{metric_id}"


def make_verified_query_doc_id(query_id: int) -> str:
    """生成已验证查询文档的稳定 ID。

    示例：``verified_query:42``
    """
    return f"verified_query:{query_id}"


def make_business_term_doc_id(term_id: str) -> str:
    """生成业务术语文档的稳定 ID。"""
    return f"business_term:{term_id}"


def doc_id_to_milvus_pk(doc_id: str) -> str:
    """把字符串文档 ID 转为 Milvus 主键字段值。

    Milvus varchar 主键支持 65535 字节，doc_id 通常远小于此限制。
    当 doc_id 超过 255 字节时（极少见）降级为 SHA-256 缩短版，保留前缀便于诊断。
    """
    if len(doc_id.encode()) <= 255:
        return doc_id
    # 保留前 40 字符 + SHA-256 前 16 字符，确保唯一性
    prefix = doc_id[:40]
    digest = sha256(doc_id.encode()).hexdigest()[:16]
    return f"{prefix}#{digest}"


# 对象类型常量，供 OpenSearch mapping 和 Milvus schema 中的 object_type 字段使用
OBJECT_TYPE_TABLE = "table"
OBJECT_TYPE_COLUMN = "column"
OBJECT_TYPE_METRIC = "metric"
OBJECT_TYPE_VERIFIED_QUERY = "verified_query"
OBJECT_TYPE_BUSINESS_TERM = "business_term"
