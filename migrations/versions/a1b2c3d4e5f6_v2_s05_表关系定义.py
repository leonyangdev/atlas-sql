"""V2-S05 表关系定义（Join Graph 的数据来源）

Revision ID: a1b2c3d4e5f6
Revises: c814be6d3a92
Create Date: 2026-09-10

新增 table_relationship 表，存储两张表之间的 JOIN 关系，供 JoinGraph 加载为内存图。

实现说明：
    cardinality / purpose 列使用 PostgreSQL 原生 ENUM 类型，但绕开 sa.Enum 的
    before_create 钩子（在 asyncpg 驱动下 create_type=False 不可靠）。

    正确流程：
    1. 用原始 SQL 查 pg_type，按需 CREATE TYPE；
    2. 建表时列用 sa.Text()，不带 server_default（避免 ALTER TYPE 时 default 冲突）；
    3. ALTER COLUMN TYPE 转换为 ENUM；
    4. ALTER COLUMN SET DEFAULT 为 ENUM 字面量。
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "c814be6d3a92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _type_exists(conn: sa.engine.Connection, type_name: str) -> bool:
    """查 pg_type 确认 ENUM 是否存在。"""
    row = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": type_name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. 按需创建 ENUM type ──────────────────────────────────────────────
    if not _type_exists(conn, "relationship_cardinality"):
        conn.execute(sa.text(
            "CREATE TYPE relationship_cardinality AS ENUM "
            "('one_to_one', 'one_to_many', 'many_to_one', 'many_to_many')"
        ))
    if not _type_exists(conn, "relationship_purpose"):
        conn.execute(sa.text(
            "CREATE TYPE relationship_purpose AS ENUM "
            "('join', 'lookup', 'agg_join', 'bridge')"
        ))

    # ── 2. 建表（cardinality/purpose 先用 Text，不带 server_default）────────
    op.create_table(
        "table_relationship",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "datasource_id",
            sa.Integer(),
            sa.ForeignKey("datasource.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_table",  sa.String(128), nullable=False),
        sa.Column("to_table",    sa.String(128), nullable=False),
        sa.Column("from_column", sa.String(128), nullable=False),
        sa.Column("to_column",   sa.String(128), nullable=False),
        # 故意不设 server_default，避免 ALTER TYPE 时 "default cannot be cast" 错误；
        # 默认值在第 4 步 SET DEFAULT 中设置。
        sa.Column("cardinality", sa.Text(), nullable=False),
        sa.Column("purpose",     sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
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

    # ── 3. ALTER 列类型为 ENUM（此时列无 default，不会冲突）─────────────────
    conn.execute(sa.text(
        "ALTER TABLE table_relationship "
        "ALTER COLUMN cardinality TYPE relationship_cardinality "
        "USING cardinality::relationship_cardinality"
    ))
    conn.execute(sa.text(
        "ALTER TABLE table_relationship "
        "ALTER COLUMN purpose TYPE relationship_purpose "
        "USING purpose::relationship_purpose"
    ))

    # ── 4. 补上默认值（现在 type 已是 ENUM，SET DEFAULT 可以直接用枚举字面量）
    conn.execute(sa.text(
        "ALTER TABLE table_relationship "
        "ALTER COLUMN cardinality SET DEFAULT 'many_to_one'"
    ))
    conn.execute(sa.text(
        "ALTER TABLE table_relationship "
        "ALTER COLUMN purpose SET DEFAULT 'join'"
    ))

    # ── 5. 按数据源索引，批量加载关系时使用 ─────────────────────────────────
    op.create_index(
        "ix_table_relationship_datasource_id", "table_relationship", ["datasource_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_table_relationship_datasource_id", table_name="table_relationship")
    op.drop_table("table_relationship")
    conn = op.get_bind()
    conn.execute(sa.text("DROP TYPE IF EXISTS relationship_purpose"))
    conn.execute(sa.text("DROP TYPE IF EXISTS relationship_cardinality"))
