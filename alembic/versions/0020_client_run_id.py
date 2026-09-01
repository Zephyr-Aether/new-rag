"""add client_run_id for run idempotency

Revision ID: 0020_client_run_id
Revises: 0019_release_order
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020_client_run_id"
down_revision: str | Sequence[str] | None = "0019_release_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """客户端幂等键：重试同一请求不重复建 run；唯一约束按租户，多 NULL 允许。"""
    op.add_column("agent_runs", sa.Column("client_run_id", sa.String(length=64), nullable=True))
    op.create_index("ix_agent_runs_client_run_id", "agent_runs", ["client_run_id"])
    op.create_unique_constraint("uq_run_client_id", "agent_runs", ["tenant_id", "client_run_id"])


def downgrade() -> None:
    op.drop_constraint("uq_run_client_id", "agent_runs", type_="unique")
    op.drop_index("ix_agent_runs_client_run_id", table_name="agent_runs")
    op.drop_column("agent_runs", "client_run_id")
