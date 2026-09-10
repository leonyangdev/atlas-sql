"""业务库迁移：建表、创建 reader 角色、授权。

职责：
1. 幂等地在业务库中创建 56 张 NovaRetail 模拟表（DDL 来自 datasets/business_migrations/）。
2. 幂等地创建 atlas_reader 只读角色并授予 SELECT 权限。

"幂等"意味着无论数据卷是全新还是复用，跑几次都安全，不会报错。
因此不需要依赖 Docker initdb 脚本的执行顺序。

用法：
    uv run python scripts/migrate_business.py
"""

import asyncio
from urllib.parse import urlsplit

import asyncpg

from datasets.migrations import apply_migrations
from server.config import get_settings


async def migrate() -> None:
    settings = get_settings()

    if settings.business_owner_database_url is None:
        raise SystemExit("ATLAS_BUSINESS_OWNER_DATABASE_URL is required for business migrations")

    owner_url = settings.business_owner_database_url.get_secret_value()

    # 从 ATLAS_BUSINESS_DATABASE_URL 中提取 reader 用户名和密码
    reader_parsed = urlsplit(settings.business_database_url.get_secret_value())
    reader_role = reader_parsed.username
    reader_password = reader_parsed.password
    if not reader_role:
        raise SystemExit("ATLAS_BUSINESS_DATABASE_URL must include the reader username")

    # 步骤 1：幂等地创建 reader 角色（角色已存在时跳过）
    await _ensure_reader_role(owner_url, reader_role, reader_password or "")

    # 步骤 2：执行 DDL 迁移（已执行过的版本自动跳过），同时刷新授权
    results = await apply_migrations(
        owner_url,
        reader_role=reader_role,
        reader_password=reader_password,
    )
    for result in results:
        print(f"{result.version}: {result.status}")


async def _ensure_reader_role(owner_url: str, role: str, password: str) -> None:
    """幂等地创建 reader 角色：已存在则跳过，不存在则创建并设置只读。"""
    dsn = owner_url.replace("postgresql+asyncpg://", "postgresql://")
    conn: asyncpg.Connection = await asyncpg.connect(dsn=dsn, timeout=10)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        if not exists:
            # 用参数化方式传密码，避免拼接 SQL
            safe_role = role.replace('"', '""')
            safe_password = password.replace("'", "''")
            await conn.execute(f"CREATE ROLE \"{safe_role}\" LOGIN PASSWORD '{safe_password}'")
            await conn.execute(f'ALTER ROLE "{safe_role}" SET default_transaction_read_only = on')
            print(f"created role: {role}")
        else:
            print(f"role already exists, skipped: {role}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
