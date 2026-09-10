"""注册默认数据源并触发一次元数据同步。

开发环境快速初始化脚本：把 nova_retail 业务库注册为数据源，
随即执行同步把所有表/列元数据采集到控制库。

用法：
    uv run python scripts/setup_datasource.py

环境要求：
    - 控制库（:5432）和业务库（:5433）均已启动且可连接
    - .env.atlas 中的连接串与 Docker Compose 保持一致
    - ATLAS_BUSINESS_OWNER_DATABASE_URL 需要有 SELECT 权限
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.config import get_settings
from server.datasource.models import DataSource, DataSourceKind, DataSourceStatus, SyncStatus
from server.datasource.sync import run_metadata_sync
from server.db import create_control_engine

# ── 默认数据源配置 ─────────────────────────────────────────────────────────
_DATASOURCE = {
    "slug": "nova-retail",
    "name": "NovaRetail Business Database",
    "kind": DataSourceKind.POSTGRESQL,
    "host": "127.0.0.1",
    "port": 5433,
    "database_name": "nova_retail",
    # credential_ref 指向环境变量，sync 时自动读取真实连接串
    # owner 账号拥有 SELECT 权限，reader 账号同样可以但 owner 更合适做初始化
    "credential_ref": "env:ATLAS_BUSINESS_OWNER_DATABASE_URL",
    "description": "NovaRetail 零售集团业务库，包含 Sales / Product / Customer 等 7 个业务域",
}


async def main() -> None:
    settings = get_settings()
    engine = create_control_engine(settings.control_database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # 1. 检查数据源是否已存在
            result = await session.execute(
                select(DataSource).where(DataSource.slug == _DATASOURCE["slug"])
            )
            ds = result.scalar_one_or_none()

            if ds is None:
                # 首次运行：注册数据源
                ds = DataSource(**_DATASOURCE, status=DataSourceStatus.ACTIVE)
                session.add(ds)
                await session.flush()
                print(f"✅ 数据源已注册：{ds.slug}（id={ds.id}）")
            else:
                print(f"ℹ️  数据源已存在，跳过注册：{ds.slug}（id={ds.id}）")

            # 2. 触发元数据同步
            from datetime import UTC, datetime

            from server.datasource.models import MetadataSyncJob
            import uuid

            job = MetadataSyncJob(
                datasource_id=ds.id,
                idempotency_key=str(uuid.uuid4()),
                status=SyncStatus.PENDING,
            )
            session.add(job)
            await session.flush()

            print(f"⏳ 开始元数据同步（job_id={job.id}）...")

            # 从环境变量解析实际连接串
            from server.datasource.credentials import CredentialError, resolve_credential
            try:
                source_url = resolve_credential(ds.credential_ref)
            except CredentialError as exc:
                print(f"❌ 凭据解析失败：{exc}")
                print("   请确认 .env.atlas 中设置了 ATLAS_BUSINESS_OWNER_DATABASE_URL")
                sys.exit(1)

            await run_metadata_sync(session, ds, job, source_url)
            await session.commit()

            if job.status == SyncStatus.SUCCEEDED:
                print(
                    f"✅ 同步完成：{job.tables_discovered} 张表，{job.columns_discovered} 列"
                )
            else:
                print(f"❌ 同步失败：{job.error_summary}")
                sys.exit(1)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
