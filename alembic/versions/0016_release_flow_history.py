"""add release_flow_history

Revision ID: 0016_release_flow_history
Revises: 0015_release_json
Create Date: 2026-08-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_release_flow_history"
down_revision: str | Sequence[str] | None = "0015_release_json"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """发布流程执行历史（留痕）：发布页每步一次执行记录。"""
    op.create_table(
        "release_flow_history",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("step", sa.String(length=32), nullable=False),
        sa.Column("operator", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        sa.Column("summary", sa.String(length=255), nullable=False, server_default=sa.text("''")),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("release_flow_history")
