"""v1_s03_s05 安全执行与 trace

Revision ID: c814be6d3a92
Revises: 6bd0c5cf42aa
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c814be6d3a92"
down_revision: str | Sequence[str] | None = "6bd0c5cf42aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("query_record", sa.Column("execution_ms", sa.Float(), nullable=True))
    op.add_column(
        "query_record",
        sa.Column(
            "referenced_tables",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "query_record",
        sa.Column(
            "referenced_columns",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "query_record",
        sa.Column("stages", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
    )
    op.add_column("query_record", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "query_record",
        sa.Column("failure_category", sa.String(length=64), nullable=True),
    )
    op.add_column("query_record", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        "query_record",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_query_record_failure_category"),
        "query_record",
        ["failure_category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_query_record_failure_category"), table_name="query_record")
    op.drop_column("query_record", "reviewed_at")
    op.drop_column("query_record", "review_note")
    op.drop_column("query_record", "failure_category")
    op.drop_column("query_record", "summary")
    op.drop_column("query_record", "stages")
    op.drop_column("query_record", "referenced_columns")
    op.drop_column("query_record", "referenced_tables")
    op.drop_column("query_record", "execution_ms")
