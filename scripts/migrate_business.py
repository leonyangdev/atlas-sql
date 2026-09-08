"""使用业务 owner 应用迁移，再保证查询 reader 获得最小 SELECT 权限。"""

import asyncio
from urllib.parse import urlsplit

from datasets.migrations import apply_migrations
from server.config import get_settings


async def migrate() -> None:
    """从脱敏配置读取两种身份，密码不会写入命令行或日志。"""

    settings = get_settings()
    if settings.business_owner_database_url is None:
        raise SystemExit("ATLAS_BUSINESS_OWNER_DATABASE_URL is required for business migrations")
    reader_role = urlsplit(settings.business_database_url.get_secret_value()).username
    if reader_role is None:
        raise SystemExit("ATLAS_BUSINESS_DATABASE_URL must include the reader user")
    results = await apply_migrations(
        settings.business_owner_database_url.get_secret_value(), reader_role=reader_role
    )
    for result in results:
        print(f"{result.version}: {result.status}")


if __name__ == "__main__":
    asyncio.run(migrate())
