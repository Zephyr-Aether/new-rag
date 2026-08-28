"""上传会话加 tenant_id：跨租户 IDOR 防护（§15.7）。"""

import sqlalchemy as sa

from alembic import op

revision = "0010_upload_session_tenant"
down_revision = "bc26410ab6cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "upload_sessions", sa.Column("tenant_id", sa.String(length=64), server_default="", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("upload_sessions", "tenant_id")
