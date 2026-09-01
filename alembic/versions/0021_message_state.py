"""add state to messages for interrupted/failed run traceback

Revision ID: 0021_message_state
Revises: 0020_client_run_id
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021_message_state"
down_revision: str | Sequence[str] | None = "0020_client_run_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """消息记录 run 终态：中断/失败的消息在历史里可被前端标记，而不是裸空气泡。"""
    op.add_column("messages", sa.Column("state", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "state")
