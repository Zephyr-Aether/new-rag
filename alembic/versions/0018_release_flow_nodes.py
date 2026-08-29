"""add release flow node configs

Revision ID: 0018_release_flow_nodes
Revises: 0017_event_dedupe_replay
Create Date: 2026-08-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018_release_flow_nodes"
down_revision: str | Sequence[str] | None = "0017_event_dedupe_replay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """发布流节点配置：5 节点（code/name）+ 每节点 config（前端回显）。"""
    op.create_table(
        "release_flow_nodes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("node_code", sa.String(length=32), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        sa.Column("config_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "agent_id", "node_code", name="uq_flow_node"),
    )


def downgrade() -> None:
    op.drop_table("release_flow_nodes")
