"""users soft delete: add isDelete column.

Revision ID: 0014_user_soft_delete
Revises: 0013_chat_docs
Create Date: 2026-08-27 00:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "0014_user_soft_delete"
down_revision = "0013_chat_docs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("isDelete", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("users", "isDelete")