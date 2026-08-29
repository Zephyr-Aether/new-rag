"""add event dedupe_hits and replay log

Revision ID: 0017_event_dedupe_replay
Revises: 0016_release_flow_history
Create Date: 2026-08-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017_event_dedupe_replay"
down_revision: str | Sequence[str] | None = "0016_release_flow_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """事件幂等命中计数 + 重放日志（成功率统计）。"""
    op.add_column(
        "events",
        sa.Column("dedupe_hits", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "event_replays",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("events_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("event_replays")
    op.drop_column("events", "dedupe_hits")
