"""把确定性行数据安全地写入本地 NovaRetail PostgreSQL，并执行质量门禁。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlsplit

import asyncpg

from datasets.generator.model import (
    BUSINESS_CLOCK,
    DATASET_VERSION,
    SCHEMA_VERSION,
    DatasetProfile,
    expected_order_amount,
    fixture_rows,
    iter_order_batches,
)
from datasets.schema.catalog import TABLES


@dataclass(frozen=True)
class SeedResult:
    """一次成功生成的摘要；大结果集只保留计数与校验和。"""

    profile: str
    row_counts: dict[str, int]
    total_rows: int
    duration_seconds: float
    snapshot_checksum: str


def validate_local_reset_target(database_url: str, confirmation: str) -> None:
    """在连接前阻止远端、错库或 reader 身份执行破坏性重置。

    CLI 仍要求显式 ``--reset``；这里是第二层保护，防止脚本被其他 Python 入口直接调用时
    绕过命令行检查。
    """

    target = urlsplit(database_url.replace("postgresql+asyncpg://", "postgresql://"))
    database = target.path.lstrip("/")
    if target.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("dataset reset is restricted to a local PostgreSQL host")
    if database != "nova_retail" or confirmation != database:
        raise ValueError("pass --confirm-database nova_retail for the local fixture database")
    if target.username == "atlas_reader":
        raise ValueError("dataset reset requires the business owner identity")


def table_columns(table_name: str) -> list[str]:
    """从 catalog 读取稳定列顺序，避免生成器和迁移各维护一份 schema。"""

    table = next(table for table in TABLES if table.name == table_name)
    return [column.name for column in table.columns]


async def copy_rows(
    connection: asyncpg.Connection[asyncpg.Record],
    table_name: str,
    rows: list[dict[str, object]],
) -> int:
    """用 PostgreSQL COPY 写入一个批次，并返回真实提交的行数。"""

    if not rows:
        return 0
    columns = table_columns(table_name)
    records = [tuple(row[column] for column in columns) for row in rows]
    await connection.copy_records_to_table(
        table_name,
        schema_name="public",
        records=records,
        columns=columns,
    )
    return len(records)


async def validate_dataset(
    connection: asyncpg.Connection[asyncpg.Record], profile: DatasetProfile
) -> dict[str, object]:
    """在事务提交前校验金额、状态、外键、库存与教学边界数据。

    任一检查失败都会抛出异常，外层事务随即回滚，因此 ``dataset_run`` 永远只记录通过门禁
    的完整快照。naive/correct 两个退款计数还把 Join 放大转成可重复的验收证据。
    """

    checks = {
        "order_amount_mismatches": await connection.fetchval(
            """
            SELECT count(*) FROM fact_order o
            JOIN (SELECT order_id, sum(net_amount) amount FROM fact_order_item GROUP BY order_id) i
              ON i.order_id = o.id
            WHERE o.order_amount <> i.amount
            """
        ),
        "payment_status_mismatches": await connection.fetchval(
            """
            SELECT count(*) FROM fact_order o
            LEFT JOIN fact_payment p ON p.order_id = o.id AND p.payment_status = 'SUCCEEDED'
            WHERE (o.order_status = 'CANCELLED' AND p.id IS NOT NULL)
               OR (o.order_status <> 'CANCELLED' AND p.id IS NULL)
            """
        ),
        "inventory_mismatches": await connection.fetchval(
            "SELECT count(*) FROM fact_inventory_snapshot "
            "WHERE available_quantity <> on_hand_quantity - reserved_quantity"
        ),
        "refund_amount_mismatches": await connection.fetchval(
            """
            SELECT count(*) FROM fact_refund r
            JOIN (
                SELECT refund_id, sum(refund_amount) amount
                FROM fact_refund_item GROUP BY refund_id
            ) i ON i.refund_id = r.id
            WHERE r.refund_amount <> i.amount
            """
        ),
        "unvalidated_foreign_keys": await connection.fetchval(
            """
            SELECT count(*) FROM pg_constraint
            WHERE contype = 'f' AND connamespace = 'public'::regnamespace AND NOT convalidated
            """
        ),
        "guest_orders": await connection.fetchval(
            "SELECT count(*) FROM fact_order WHERE customer_id IS NULL"
        ),
        "test_orders": await connection.fetchval("SELECT count(*) FROM fact_order WHERE is_test"),
        "cancelled_orders": await connection.fetchval(
            "SELECT count(*) FROM fact_order WHERE order_status = 'CANCELLED'"
        ),
        "minimum_ordered_at": str(
            await connection.fetchval("SELECT min(ordered_at) FROM fact_order")
        ),
        "maximum_ordered_at": str(
            await connection.fetchval("SELECT max(ordered_at) FROM fact_order")
        ),
        "duplicate_product_names": await connection.fetchval(
            "SELECT count(*) FROM (SELECT product_name FROM dim_product "
            "GROUP BY product_name HAVING count(*) > 1) names"
        ),
        "naive_refund_join_rows": await connection.fetchval(
            """
            SELECT count(*) FROM fact_order o
            JOIN fact_order_item oi ON oi.order_id = o.id
            JOIN fact_refund r ON r.order_id = o.id
            JOIN fact_refund_item ri ON ri.refund_id = r.id
            """
        ),
        "correct_refund_item_rows": await connection.fetchval(
            "SELECT count(*) FROM fact_refund_item"
        ),
    }
    if checks["order_amount_mismatches"] or checks["payment_status_mismatches"]:
        raise RuntimeError(f"sales reconciliation failed: {checks}")
    if checks["inventory_mismatches"] or checks["refund_amount_mismatches"]:
        raise RuntimeError(f"inventory reconciliation failed: {checks}")
    if checks["unvalidated_foreign_keys"]:
        raise RuntimeError(f"foreign-key validation failed: {checks}")
    if checks["guest_orders"] == 0 or checks["test_orders"] == 0:
        raise RuntimeError("required NULL and test-order boundary data is missing")
    if checks["duplicate_product_names"] == 0:
        raise RuntimeError("duplicate product-name fixture is missing")
    if checks["naive_refund_join_rows"] <= checks["correct_refund_item_rows"]:
        raise RuntimeError("refund join-amplification fixture is missing")
    item_count = await connection.fetchval("SELECT count(*) FROM fact_order_item")
    if item_count != profile.order_item_count:
        raise RuntimeError("generated order-item count does not match the selected profile")
    hand_fixture_amount = await connection.fetchval(
        "SELECT order_amount FROM fact_order WHERE id = 1"
    )
    expected = expected_order_amount(1, profile.items_per_order, profile.seed)
    if hand_fixture_amount != expected:
        raise RuntimeError(f"hand fixture expected {expected}, found {hand_fixture_amount}")
    checks["hand_fixture_order_amount"] = str(hand_fixture_amount)
    return checks


async def snapshot_checksum(connection: asyncpg.Connection[asyncpg.Record]) -> str:
    """对稳定业务摘要计算校验和，不读取或保存百万行明细。"""

    summary = await connection.fetchrow(
        """
        SELECT count(*) order_count,
               coalesce(sum(order_amount), 0)::text order_amount,
               count(*) FILTER (WHERE is_test) test_orders,
               count(*) FILTER (WHERE customer_id IS NULL) guest_orders,
               min(ordered_at)::text first_order,
               max(ordered_at)::text last_order
        FROM fact_order
        """
    )
    return sha256(json.dumps(dict(summary), sort_keys=True).encode()).hexdigest()


async def seed_database(database_url: str, profile: DatasetProfile) -> SeedResult:
    """在单个事务内重建、验证并登记一个数据快照。

    维度和固定夹具先写入，随后按“订单 → 明细 → 支付 → 退款”顺序逐批 COPY。任何异常都会
    回滚 TRUNCATE 和已写批次，调用方不会看到半新半旧的数据。
    """

    started = time.monotonic()
    connection = await asyncpg.connect(
        database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    row_counts: dict[str, int] = {}
    try:
        migration = await connection.fetchval(
            "SELECT max(version) FROM atlas_internal.business_schema_migration"
        )
        if migration != SCHEMA_VERSION:
            raise RuntimeError(f"expected business schema {SCHEMA_VERSION}, found {migration}")
        table_list = ", ".join(f'public."{table.name}"' for table in TABLES)
        async with connection.transaction():
            await connection.execute(f"TRUNCATE TABLE {table_list} CASCADE")
            for table_name, rows in fixture_rows().items():
                row_counts[table_name] = await copy_rows(connection, table_name, rows)
            for batch in iter_order_batches(profile):
                for table_name, rows in (
                    ("fact_order", batch.orders),
                    ("fact_order_item", batch.items),
                    ("fact_payment", batch.payments),
                    ("fact_refund", batch.refunds),
                    ("fact_refund_item", batch.refund_items),
                ):
                    row_counts[table_name] = row_counts.get(table_name, 0) + await copy_rows(
                        connection, table_name, rows
                    )
            checks = await validate_dataset(connection, profile)
            checksum = await snapshot_checksum(connection)
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS atlas_internal.dataset_run (
                    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    dataset_version text NOT NULL,
                    schema_version text NOT NULL,
                    profile text NOT NULL,
                    seed bigint NOT NULL,
                    business_clock timestamptz NOT NULL,
                    row_counts jsonb NOT NULL,
                    validation_summary jsonb NOT NULL,
                    snapshot_checksum char(64) NOT NULL,
                    generated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            await connection.execute(
                """
                INSERT INTO atlas_internal.dataset_run(
                    dataset_version, schema_version, profile, seed, business_clock,
                    row_counts, validation_summary, snapshot_checksum
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
                """,
                DATASET_VERSION,
                SCHEMA_VERSION,
                profile.name,
                profile.seed,
                BUSINESS_CLOCK,
                json.dumps(row_counts, sort_keys=True),
                json.dumps(checks, sort_keys=True),
                checksum,
            )
    finally:
        await connection.close()
    duration = time.monotonic() - started
    return SeedResult(profile.name, row_counts, sum(row_counts.values()), duration, checksum)
