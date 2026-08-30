"""add release order table and flow-history order link

Revision ID: 0019_release_order
Revises: 0018_release_flow_nodes
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019_release_order"
down_revision: str | Sequence[str] | None = "0018_release_flow_nodes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """发布单：一次发布周期的正式记录；留痕挂到单号下。"""
    op.create_table(
        "release_order",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("order_no", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        sa.Column("summary", sa.String(length=255), nullable=False, server_default=sa.text("''")),
        sa.Column("snapshot_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "agent_id", "order_no", name="uq_release_order_no"),
    )
    op.add_column("release_flow_history", sa.Column("order_id", sa.String(length=64), nullable=True))
    op.create_index("ix_release_flow_history_order_id", "release_flow_history", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_release_flow_history_order_id", table_name="release_flow_history")
    op.drop_column("release_flow_history", "order_id")
    op.drop_table("release_order")
