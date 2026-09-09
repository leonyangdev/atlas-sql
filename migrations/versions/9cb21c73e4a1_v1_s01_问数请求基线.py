"""V1-S01 问数请求基线

Revision ID: 9cb21c73e4a1
Revises: 6bdae843a9d5
Create Date: 2026-09-09 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9cb21c73e4a1"
down_revision: str | Sequence[str] | None = "6bdae843a9d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建可按 trace_id 追踪的问数请求记录。"""

    op.create_table(
        "query_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("identity", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PROCESSING",
                "SUCCEEDED",
                "CLARIFICATION_REQUIRED",
                "REJECTED",
                "FAILED",
                name="query_status",
            ),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("columns", sa.JSON(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("metric_ids", sa.JSON(), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_query_record_identity"), "query_record", ["identity"], unique=False)
    op.create_index(
        op.f("ix_query_record_session_id"), "query_record", ["session_id"], unique=False
    )
    op.create_index(op.f("ix_query_record_trace_id"), "query_record", ["trace_id"], unique=True)


def downgrade() -> None:
    """移除问数请求记录和枚举类型。"""

    op.drop_index(op.f("ix_query_record_trace_id"), table_name="query_record")
    op.drop_index(op.f("ix_query_record_session_id"), table_name="query_record")
    op.drop_index(op.f("ix_query_record_identity"), table_name="query_record")
    op.drop_table("query_record")
    sa.Enum(name="query_status").drop(op.get_bind())
