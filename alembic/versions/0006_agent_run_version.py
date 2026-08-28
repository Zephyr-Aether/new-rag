"""§3.3 agent_runs.version 乐观锁列（CAS 版本号）。"""

import sqlalchemy as sa

from alembic import op

revision = "0006_agent_run_version"
down_revision = "0005_release_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 存量 run 回落 version=1；后续 set_state 原子自增
    op.add_column(
        "agent_runs",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "version")
