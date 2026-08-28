"""补齐 users.password_hash：模型有但初始迁移遗漏，alembic 管理库登录所需（§27）。"""

import sqlalchemy as sa

from alembic import op

revision = "0009_user_password_hash"
down_revision = "0008_identity_users_secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
