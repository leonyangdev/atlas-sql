"""从 PostgreSQL 采集表、列、键、索引等元数据。

Inspector 只负责读取源库结构，不写控制库。采集结果以纯数据类返回，由调用方决定
如何落库，确保逻辑可以在单测中不启动数据库验证。

样例值采集会主动跳过敏感性较高的列，避免把真实业务数据写入控制库。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import asyncpg


@dataclass(frozen=True)
class ColumnInfo:
    """单列的结构化描述，源自 information_schema 与 pg_catalog 联合查询。"""

    column_name: str
    ordinal_position: int
    data_type: str
    character_maximum_length: int | None
    numeric_precision: int | None
    numeric_scale: int | None
    is_nullable: bool
    column_default: str | None
    is_primary_key: bool
    # "schema.table.column" 格式，无外键时为 None
    foreign_key_ref: str | None
    raw_comment: str | None
    # 已脱敏的样例值列表（最多 10 个）；高敏感列此字段留空列表
    sample_values: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TableInfo:
    """单张表的元数据，包含全部列。"""

    schema_name: str
    table_name: str
    table_type: str  # "TABLE" 或 "VIEW"
    row_estimate: int | None
    raw_comment: str | None
    columns: list[ColumnInfo] = field(default_factory=list)


# 采集样例值时跳过这些 PostgreSQL 系统 schema
_EXCLUDED_SCHEMAS = frozenset({"information_schema", "pg_catalog", "pg_toast", "pg_temp"})

# 采集样例值时跳过明显含有敏感信息的列名模式（不区分大小写）
_SENSITIVE_COLUMN_PATTERNS = (
    "password",
    "passwd",
    "secret",
    "token",
    "hash",
    "salt",
    "credit_card",
    "ssn",
    "mobile",
    "phone",
    "email",
)


def _is_sensitive_column(column_name: str) -> bool:
    """简单检查列名是否匹配敏感模式，跳过样例值采集。"""
    name_lower = column_name.lower()
    return any(pattern in name_lower for pattern in _SENSITIVE_COLUMN_PATTERNS)


async def collect_tables(
    connection: asyncpg.Connection[asyncpg.Record],
    schema_name: str = "public",
    include_views: bool = True,
    max_sample_values: int = 10,
) -> list[TableInfo]:
    """采集指定 schema 下的全部表和列信息。

    使用 information_schema 保证跨 PostgreSQL 版本兼容；行估算使用 pg_stat_user_tables
    的 n_live_tup，比 COUNT(*) 快得多但是近似值。

    Args:
        connection: 已建立的数据库连接（需要有 SELECT on information_schema 权限）。
        schema_name: 目标 schema，默认 public。
        include_views: 是否同时采集视图。
        max_sample_values: 每列最多采集多少个样例值。

    Returns:
        包含列信息的表列表，顺序按表名排序。
    """
    table_types = ("'BASE TABLE'", "'VIEW'") if include_views else ("'BASE TABLE'",)
    type_filter = ", ".join(table_types)

    # 一次查询取表基本信息和行估算
    table_rows = await connection.fetch(
        f"""
        SELECT
            t.table_schema,
            t.table_name,
            t.table_type,
            COALESCE(s.n_live_tup::integer, 0) AS row_estimate,
            obj_description(c.oid, 'pg_class') AS raw_comment
        FROM information_schema.tables t
        LEFT JOIN pg_class c
            ON c.relname = t.table_name
            AND c.relnamespace = (
                SELECT oid FROM pg_namespace WHERE nspname = t.table_schema
            )
        LEFT JOIN pg_stat_user_tables s
            ON s.schemaname = t.table_schema AND s.relname = t.table_name
        WHERE t.table_schema = $1
          AND t.table_type IN ({type_filter})
        ORDER BY t.table_name
        """,
        schema_name,
    )

    if not table_rows:
        return []

    table_names = [row["table_name"] for row in table_rows]

    # 批量取主键信息
    pk_rows = await connection.fetch(
        """
        SELECT kcu.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tc.constraint_name
            AND kcu.table_schema = tc.table_schema
        WHERE tc.table_schema = $1
          AND tc.constraint_type = 'PRIMARY KEY'
          AND kcu.table_name = ANY($2::text[])
        """,
        schema_name,
        table_names,
    )
    primary_keys: dict[str, set[str]] = {}
    for row in pk_rows:
        primary_keys.setdefault(row["table_name"], set()).add(row["column_name"])

    # 批量取外键信息
    fk_rows = await connection.fetch(
        """
        SELECT
            kcu.table_name,
            kcu.column_name,
            ccu.table_schema AS ref_schema,
            ccu.table_name  AS ref_table,
            ccu.column_name AS ref_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tc.constraint_name
            AND kcu.table_schema = tc.table_schema
        JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.table_schema = $1
          AND tc.constraint_type = 'FOREIGN KEY'
          AND kcu.table_name = ANY($2::text[])
        """,
        schema_name,
        table_names,
    )
    # key: (table_name, column_name) -> "ref_schema.ref_table.ref_column"
    foreign_keys: dict[tuple[str, str], str] = {}
    for row in fk_rows:
        key = (row["table_name"], row["column_name"])
        foreign_keys[key] = f"{row['ref_schema']}.{row['ref_table']}.{row['ref_column']}"

    # 批量取列信息
    col_rows = await connection.fetch(
        """
        SELECT
            c.table_name,
            c.column_name,
            c.ordinal_position,
            c.data_type,
            c.character_maximum_length,
            c.numeric_precision,
            c.numeric_scale,
            c.is_nullable,
            c.column_default,
            col_description(
                (SELECT oid FROM pg_class WHERE relname = c.table_name
                 AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = c.table_schema)),
                c.ordinal_position
            ) AS raw_comment
        FROM information_schema.columns c
        WHERE c.table_schema = $1
          AND c.table_name = ANY($2::text[])
        ORDER BY c.table_name, c.ordinal_position
        """,
        schema_name,
        table_names,
    )

    # 按表名分组列信息
    columns_by_table: dict[str, list[ColumnInfo]] = {name: [] for name in table_names}
    for row in col_rows:
        tname = row["table_name"]
        cname = row["column_name"]
        col = ColumnInfo(
            column_name=cname,
            ordinal_position=row["ordinal_position"],
            data_type=row["data_type"],
            character_maximum_length=row["character_maximum_length"],
            numeric_precision=row["numeric_precision"],
            numeric_scale=row["numeric_scale"],
            is_nullable=row["is_nullable"] == "YES",
            column_default=row["column_default"],
            is_primary_key=cname in primary_keys.get(tname, set()),
            foreign_key_ref=foreign_keys.get((tname, cname)),
            raw_comment=row["raw_comment"],
        )
        columns_by_table[tname].append(col)

    # 采集样例值（只采非敏感列，且每张表不超过 max_sample_values 个列）
    if max_sample_values > 0:
        for tname, cols in columns_by_table.items():
            for col in cols:
                if _is_sensitive_column(col.column_name):
                    continue
                try:
                    samples = await _collect_sample_values(
                        connection, schema_name, tname, col.column_name, max_sample_values
                    )
                    # ColumnInfo 是 frozen dataclass，需要替换整个对象
                    idx = columns_by_table[tname].index(col)
                    columns_by_table[tname][idx] = ColumnInfo(
                        column_name=col.column_name,
                        ordinal_position=col.ordinal_position,
                        data_type=col.data_type,
                        character_maximum_length=col.character_maximum_length,
                        numeric_precision=col.numeric_precision,
                        numeric_scale=col.numeric_scale,
                        is_nullable=col.is_nullable,
                        column_default=col.column_default,
                        is_primary_key=col.is_primary_key,
                        foreign_key_ref=col.foreign_key_ref,
                        raw_comment=col.raw_comment,
                        sample_values=samples,
                    )
                except Exception:  # noqa: BLE001
                    # 样例值采集是尽力而为，失败不阻断整体同步
                    pass

    # 组装 TableInfo
    result: list[TableInfo] = []
    for row in table_rows:
        tname = row["table_name"]
        result.append(
            TableInfo(
                schema_name=schema_name,
                table_name=tname,
                table_type="VIEW" if row["table_type"] == "VIEW" else "TABLE",
                row_estimate=row["row_estimate"] or None,
                raw_comment=row["raw_comment"],
                columns=columns_by_table.get(tname, []),
            )
        )
    return result


async def _collect_sample_values(
    connection: asyncpg.Connection[asyncpg.Record],
    schema_name: str,
    table_name: str,
    column_name: str,
    limit: int,
) -> list[str]:
    """从指定列采集不重复的样例值，转为字符串列表。

    使用 TABLESAMPLE BERNOULLI 采集避免全表扫描；样例数量较少时可能无法满足 limit，
    这是可接受的行为。
    """
    # 标识符安全处理：只允许字母、数字和下划线
    for identifier in (schema_name, table_name, column_name):
        if not all(c.isalnum() or c == "_" for c in identifier):
            return []

    rows = await connection.fetch(
        f"""
        SELECT DISTINCT "{column_name}"::text AS val
        FROM "{schema_name}"."{table_name}" TABLESAMPLE BERNOULLI(10)
        WHERE "{column_name}" IS NOT NULL
        LIMIT {limit}
        """
    )
    return [row["val"] for row in rows if row["val"] is not None]


def serialize_sample_values(values: list[str]) -> str:
    """把样例值列表序列化为存储在控制库的 JSON 字符串。"""
    return json.dumps(values, ensure_ascii=False)
