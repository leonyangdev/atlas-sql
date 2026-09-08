"""确定性数据生成 CLI；所有会清空数据的参数都必须显式提供。"""

import argparse
import asyncio

from datasets.generator.database import seed_database, validate_local_reset_target
from datasets.generator.model import PROFILES
from server.config import get_settings


def arguments() -> argparse.Namespace:
    """解析规模和双重重置确认参数。"""

    parser = argparse.ArgumentParser(description="Generate deterministic NovaRetail test data")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="tiny")
    parser.add_argument("--reset", action="store_true", help="replace all existing fixture rows")
    parser.add_argument("--confirm-database", help="must equal nova_retail")
    return parser.parse_args()


async def main() -> None:
    """验证环境与目标后生成快照，只输出不含业务明细的摘要。"""

    args = arguments()
    if not args.reset:
        raise SystemExit("--reset is required because generation replaces the fixture snapshot")
    settings = get_settings()
    if settings.environment != "development":
        raise SystemExit("fixture generation is restricted to ATLAS_ENVIRONMENT=development")
    if settings.business_owner_database_url is None:
        raise SystemExit("ATLAS_BUSINESS_OWNER_DATABASE_URL is required")
    url = settings.business_owner_database_url.get_secret_value()
    try:
        validate_local_reset_target(url, args.confirm_database or "")
    except ValueError as error:
        raise SystemExit(str(error)) from error
    result = await seed_database(url, PROFILES[args.profile])
    print(
        f"profile={result.profile} rows={result.total_rows} "
        f"seconds={result.duration_seconds:.2f} checksum={result.snapshot_checksum}"
    )


if __name__ == "__main__":
    asyncio.run(main())
