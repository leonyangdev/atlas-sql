"""V3-S01 语义层基础表

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-10

新增以下表，支持 V3 业务语义与可信查询：
- metric_definition        指标定义主表
- metric_version           指标版本快照（不可变）
- metric_active_version    当前生效版本指针
- semantic_dimension       语义维度定义
- business_glossary        业务术语与同义词
- fiscal_calendar          财年日历
- verified_query           已验证的问题-SQL 样例
- semantic_index_record    向量/词法索引版本记录

ENUM 处理与 V2-S05 一致：
  先用原始 SQL 按需 CREATE TYPE，建表时列用 Text，
  再 ALTER COLUMN TYPE 转为 ENUM，最后 SET DEFAULT。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _type_exists(conn: sa.engine.Connection, type_name: str) -> bool:
    row = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": type_name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. 按需创建 ENUM type ──────────────────────────────────────────────

    if not _type_exists(conn, "semantic_status"):
        conn.execute(
            sa.text(
                "CREATE TYPE semantic_status AS ENUM "
                "('draft', 'testing', 'published', 'deprecated')"
            )
        )

    if not _type_exists(conn, "metric_grain"):
        conn.execute(
            sa.text(
                "CREATE TYPE metric_grain AS ENUM "
                "('order_item', 'order', 'customer', 'period', 'snapshot_date', 'warehouse_sku')"
            )
        )

    if not _type_exists(conn, "time_role"):
        conn.execute(
            sa.text(
                "CREATE TYPE time_role AS ENUM "
                "('paid_at', 'refunded_at', 'created_at', 'event_at', 'snapshot_date')"
            )
        )

    if not _type_exists(conn, "zero_denominator_policy"):
        conn.execute(
            sa.text(
                "CREATE TYPE zero_denominator_policy AS ENUM "
                "('null_with_reason', 'zero', 'not_applicable')"
            )
        )

    if not _type_exists(conn, "dimension_type"):
        conn.execute(
            sa.text(
                "CREATE TYPE dimension_type AS ENUM "
                "('time', 'categorical', 'hierarchical', 'geography', 'customer_segment')"
            )
        )

    if not _type_exists(conn, "glossary_status"):
        conn.execute(
            sa.text("CREATE TYPE glossary_status AS ENUM ('active', 'deprecated')")
        )

    if not _type_exists(conn, "verified_query_status"):
        conn.execute(
            sa.text(
                "CREATE TYPE verified_query_status AS ENUM ('draft', 'verified', 'invalid')"
            )
        )

    # ── 2. metric_definition ──────────────────────────────────────────────

    op.create_table(
        "metric_definition",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("metric_id", sa.String(128), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("grain", sa.Text(), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("required_filters", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("dependent_columns", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("allowed_dimensions", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("time_role", sa.Text(), nullable=False),
        sa.Column("zero_denominator_policy", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("synonyms", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("time_rule_note", sa.Text(), nullable=True),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("metric_id", name="uq_metric_definition_metric_id"),
    )
    op.create_index("ix_metric_definition_metric_id", "metric_definition", ["metric_id"])
    op.create_index("ix_metric_definition_domain", "metric_definition", ["domain"])

    # ALTER 列类型为 ENUM
    for col, enum_type, default in [
        ("grain", "metric_grain", "period"),
        ("time_role", "time_role", "paid_at"),
        ("zero_denominator_policy", "zero_denominator_policy", "not_applicable"),
        ("status", "semantic_status", "draft"),
    ]:
        conn.execute(
            sa.text(
                f"ALTER TABLE metric_definition "
                f"ALTER COLUMN {col} TYPE {enum_type} "
                f"USING {col}::{enum_type}"
            )
        )
        conn.execute(
            sa.text(f"ALTER TABLE metric_definition ALTER COLUMN {col} SET DEFAULT '{default}'")
        )

    # ── 3. metric_version ──────────────────────────────────────────────────

    op.create_table(
        "metric_version",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "metric_id",
            sa.String(128),
            sa.ForeignKey("metric_definition.metric_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("regression_run_id", sa.String(128), nullable=True),
        sa.Column("published_by", sa.String(128), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("metric_id", "version_number", name="uq_metric_version"),
    )
    op.create_index("ix_metric_version_metric_id", "metric_version", ["metric_id"])

    # ── 4. metric_active_version ──────────────────────────────────────────

    op.create_table(
        "metric_active_version",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "metric_id",
            sa.String(128),
            sa.ForeignKey("metric_definition.metric_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("metric_id", name="uq_metric_active_version_metric_id"),
    )
    op.create_index(
        "ix_metric_active_version_metric_id", "metric_active_version", ["metric_id"]
    )

    # ── 5. semantic_dimension ─────────────────────────────────────────────

    op.create_table(
        "semantic_dimension",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dimension_id", sa.String(128), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("dimension_type", sa.Text(), nullable=False),
        sa.Column("column_refs", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("synonyms", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("hierarchy_levels", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dimension_id", name="uq_dimension_id"),
    )
    op.create_index("ix_semantic_dimension_dimension_id", "semantic_dimension", ["dimension_id"])
    op.create_index("ix_semantic_dimension_domain", "semantic_dimension", ["domain"])

    for col, enum_type, default in [
        ("dimension_type", "dimension_type", "categorical"),
        ("status", "semantic_status", "draft"),
    ]:
        conn.execute(
            sa.text(
                f"ALTER TABLE semantic_dimension "
                f"ALTER COLUMN {col} TYPE {enum_type} "
                f"USING {col}::{enum_type}"
            )
        )
        conn.execute(
            sa.text(f"ALTER TABLE semantic_dimension ALTER COLUMN {col} SET DEFAULT '{default}'")
        )

    # ── 6. business_glossary ──────────────────────────────────────────────

    op.create_table(
        "business_glossary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("term", sa.String(256), nullable=False),
        sa.Column("canonical_target_id", sa.String(256), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("mapped_value", sa.String(512), nullable=True),
        sa.Column("domain", sa.String(64), nullable=True),
        sa.Column("owner", sa.String(128), nullable=True),
        sa.Column("authoritative_source", sa.String(256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_glossary_term", "business_glossary", ["term"])
    op.create_index("ix_business_glossary_domain", "business_glossary", ["domain"])

    conn.execute(
        sa.text(
            "ALTER TABLE business_glossary "
            "ALTER COLUMN status TYPE glossary_status "
            "USING status::glossary_status"
        )
    )
    conn.execute(
        sa.text("ALTER TABLE business_glossary ALTER COLUMN status SET DEFAULT 'active'")
    )

    # ── 7. fiscal_calendar ────────────────────────────────────────────────

    op.create_table(
        "fiscal_calendar",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fiscal_year", sa.String(16), nullable=False),
        sa.Column("domain", sa.String(64), nullable=True),
        sa.Column("start_month_day", sa.String(5), nullable=False),
        sa.Column("end_month_day", sa.String(5), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fiscal_calendar_fiscal_year", "fiscal_calendar", ["fiscal_year"])
    op.create_index("ix_fiscal_calendar_domain", "fiscal_calendar", ["domain"])

    # ── 8. verified_query ─────────────────────────────────────────────────

    op.create_table(
        "verified_query",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("query_id", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("semantic_version_ref", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(64), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dependent_metric_ids", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("is_test_locked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("verified_by", sa.String(128), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_validation_result", sa.String(16), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_id", name="uq_verified_query_id"),
    )
    op.create_index("ix_verified_query_query_id", "verified_query", ["query_id"])
    op.create_index("ix_verified_query_domain", "verified_query", ["domain"])
    op.create_index("ix_verified_query_status", "verified_query", ["status"])

    conn.execute(
        sa.text(
            "ALTER TABLE verified_query "
            "ALTER COLUMN status TYPE verified_query_status "
            "USING status::verified_query_status"
        )
    )
    conn.execute(
        sa.text("ALTER TABLE verified_query ALTER COLUMN status SET DEFAULT 'draft'")
    )

    # ── 9. semantic_index_record ──────────────────────────────────────────

    op.create_table(
        "semantic_index_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(128), nullable=False),
        sa.Column("index_version", sa.String(64), nullable=False),
        sa.Column("is_indexed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_semantic_index_object",
        "semantic_index_record",
        ["object_type", "object_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_semantic_index_object", table_name="semantic_index_record")
    op.drop_table("semantic_index_record")

    op.drop_index("ix_verified_query_status", table_name="verified_query")
    op.drop_index("ix_verified_query_domain", table_name="verified_query")
    op.drop_index("ix_verified_query_query_id", table_name="verified_query")
    op.drop_table("verified_query")

    op.drop_index("ix_fiscal_calendar_domain", table_name="fiscal_calendar")
    op.drop_index("ix_fiscal_calendar_fiscal_year", table_name="fiscal_calendar")
    op.drop_table("fiscal_calendar")

    op.drop_index("ix_business_glossary_domain", table_name="business_glossary")
    op.drop_index("ix_business_glossary_term", table_name="business_glossary")
    op.drop_table("business_glossary")

    op.drop_index("ix_semantic_dimension_domain", table_name="semantic_dimension")
    op.drop_index("ix_semantic_dimension_dimension_id", table_name="semantic_dimension")
    op.drop_table("semantic_dimension")

    op.drop_index("ix_metric_active_version_metric_id", table_name="metric_active_version")
    op.drop_table("metric_active_version")

    op.drop_index("ix_metric_version_metric_id", table_name="metric_version")
    op.drop_table("metric_version")

    op.drop_index("ix_metric_definition_domain", table_name="metric_definition")
    op.drop_index("ix_metric_definition_metric_id", table_name="metric_definition")
    op.drop_table("metric_definition")

    conn = op.get_bind()
    for t in [
        "verified_query_status",
        "glossary_status",
        "dimension_type",
        "zero_denominator_policy",
        "time_role",
        "metric_grain",
        "semantic_status",
    ]:
        conn.execute(sa.text(f"DROP TYPE IF EXISTS {t}"))
