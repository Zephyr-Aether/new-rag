"""对话持久化（§10）：messages 表 + sessions.title。"""

import sqlalchemy as sa

from alembic import op

revision = "0011_chat_sessions"
down_revision = "0010_upload_session_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("title", sa.String(length=255), server_default="", nullable=False))
    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tools_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_messages_session_id"), "messages", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_session_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_column("sessions", "title")
