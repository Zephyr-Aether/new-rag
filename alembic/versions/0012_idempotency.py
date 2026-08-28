"""API 级幂等：idempotency 表（Idempotency-Key 重放去重）。"""

import sqlalchemy as sa

from alembic import op

revision = "0012_idempotency"
down_revision = "0011_chat_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency",
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("status_code", sa.Integer(), server_default="200", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("idempotency")
