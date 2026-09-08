"""NovaRetail 业务库的迁移生成与执行。

控制库继续使用 Alembic；业务库的 56 张模拟表由声明式 catalog 生成 SQL。两套迁移分开，
是为了让学习者清楚区分 AtlasSQL 自己的数据与被分析的业务数据。
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from datasets.schema.catalog import TABLES, Table

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
MIGRATION_ROOT = Path(__file__).with_name("business_migrations")


@dataclass(frozen=True)
class MigrationResult:
    """单个迁移的执行结果，用于 CLI 输出和验收记录。"""

    version: str
    status: str


def quote_identifier(value: str) -> str:
    """只允许 catalog 约定的小写标识符，避免把动态名称直接拼入 SQL。"""

    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value}")
    return f'"{value}"'


def render_schema_sql(tables: tuple[Table, ...] = TABLES) -> str:
    """把 catalog 渲染为确定性的 PostgreSQL 建表脚本。

    先创建全部表，再添加外键，可处理跨域引用和互相引用。每个外键同时建立索引，避免后续
    Join 和删除父记录时出现不必要的全表扫描。
    """

    statements = ["SET lock_timeout = '10s';", "SET statement_timeout = '5min';"]
    for table in tables:
        columns = []
        for item in table.columns:
            nullable = "" if item.nullable else " NOT NULL"
            columns.append(f"  {quote_identifier(item.name)} {item.data_type}{nullable}")
        primary_key = next(item for item in table.columns if item.is_primary_key)
        columns.append(f"  PRIMARY KEY ({quote_identifier(primary_key.name)})")
        for name, values in sorted(table.status_enums.items()):
            allowed = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
            columns.append(f"  CHECK ({quote_identifier(name)} IN ({allowed}))")
        statements.append(
            f"CREATE TABLE public.{quote_identifier(table.name)} (\n" + ",\n".join(columns) + "\n);"
        )

    for table in tables:
        for item in table.columns:
            if item.reference is None:
                continue
            target_table, target_column = item.reference.split(".", 1)
            constraint = f"fk_{table.name}_{item.name}"
            statements.append(
                f"ALTER TABLE public.{quote_identifier(table.name)} "
                f"ADD CONSTRAINT {quote_identifier(constraint)} "
                f"FOREIGN KEY ({quote_identifier(item.name)}) "
                f"REFERENCES public.{quote_identifier(target_table)} "
                f"({quote_identifier(target_column)});"
            )
            statements.append(
                f"CREATE INDEX {quote_identifier(f'idx_{table.name}_{item.name}')} "
                f"ON public.{quote_identifier(table.name)} ({quote_identifier(item.name)});"
            )
    return "\n\n".join(statements) + "\n"


def migration_files(root: Path = MIGRATION_ROOT) -> list[Path]:
    """按三位版本号排序迁移，忽略说明文档等非 SQL 文件。"""

    return sorted(root.glob("[0-9][0-9][0-9]_*.sql"))


async def apply_migrations(
    database_url: str,
    root: Path = MIGRATION_ROOT,
    reader_role: str | None = None,
) -> list[MigrationResult]:
    """串行执行尚未应用的迁移，并在每次运行后修复 reader 授权。

    advisory lock 防止两个开发进程同时迁移。已执行迁移的 SHA-256 必须保持不变；需要修改
    schema 时应新增版本，而不是重写历史。reader 授权放在迁移器里，可以覆盖已有 Docker
    命名卷和先初始化角色、后建表两种顺序。
    """

    connection = await asyncpg.connect(
        database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    results: list[MigrationResult] = []
    try:
        await connection.execute("CREATE SCHEMA IF NOT EXISTS atlas_internal")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS atlas_internal.business_schema_migration (
                version text PRIMARY KEY,
                checksum char(64) NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        for path in migration_files(root):
            version = path.name.split("_", 1)[0]
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", 247_285_730)
                existing = await connection.fetchval(
                    "SELECT checksum FROM atlas_internal.business_schema_migration "
                    "WHERE version=$1",
                    version,
                )
                if existing is not None:
                    if existing != checksum:
                        raise RuntimeError(f"migration {version} changed after it was applied")
                    results.append(MigrationResult(version, "skipped"))
                    continue
                await connection.execute(sql)
                await connection.execute(
                    "INSERT INTO atlas_internal.business_schema_migration(version, checksum) "
                    "VALUES ($1, $2)",
                    version,
                    checksum,
                )
                results.append(MigrationResult(version, "applied"))
        if reader_role is not None:
            role = quote_identifier(reader_role)
            await connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            await connection.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
            await connection.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}")
            await connection.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {role}"
            )
    finally:
        await connection.close()
    return results
