"""V1-S02 模型生成追踪

Revision ID: 6bd0c5cf42aa
Revises: 9cb21c73e4a1
Create Date: 2026-09-09 21:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6bd0c5cf42aa"
down_revision: str | Sequence[str] | None = "9cb21c73e4a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 query_record 增加可复现的模型调用元数据。"""

    op.add_column("query_record", sa.Column("prompt_version", sa.String(64), nullable=True))
    op.add_column("query_record", sa.Column("prompt_hash", sa.String(64), nullable=True))
    op.add_column(
        "query_record",
        sa.Column("model_parameters", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "query_record", sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "query_record", sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "query_record", sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("query_record", sa.Column("provider_request_id", sa.String(128), nullable=True))
    op.create_index(
        op.f("ix_query_record_prompt_hash"), "query_record", ["prompt_hash"], unique=False
    )


def downgrade() -> None:
    """移除 V1-S02 模型调用元数据。"""

    op.drop_index(op.f("ix_query_record_prompt_hash"), table_name="query_record")
    op.drop_column("query_record", "provider_request_id")
    op.drop_column("query_record", "total_tokens")
    op.drop_column("query_record", "output_tokens")
    op.drop_column("query_record", "input_tokens")
    op.drop_column("query_record", "model_parameters")
    op.drop_column("query_record", "prompt_hash")
    op.drop_column("query_record", "prompt_version")
