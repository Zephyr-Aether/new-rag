"""Phase 1 身份：users 加 enabled / must_change_password；新增 secrets 表（§6.5 加密落库）。"""

import sqlalchemy as sa

from alembic import op

revision = "0008_identity_users_secrets"
down_revision = "0007_llm_token_breakdown"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column(
        "users", sa.Column("must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.create_table(
        "secrets",
        sa.Column("ref", sa.String(length=128), primary_key=True),
        sa.Column("value_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("secrets")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "enabled")
