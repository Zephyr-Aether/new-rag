"""会话消息加引用来源：messages.docs_json。"""

import sqlalchemy as sa

from alembic import op

revision = "0013_chat_docs"
down_revision = "0012_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("docs_json", sa.Text(), server_default="[]", nullable=False))


def downgrade() -> None:
    op.drop_column("messages", "docs_json")
