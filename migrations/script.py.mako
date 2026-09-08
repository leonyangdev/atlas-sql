"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """把控制库从上一版本升级到本版本。"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """仅在变更可安全回滚时实现降级；生成后需要人工审查。"""
    ${downgrades if downgrades else "pass"}
