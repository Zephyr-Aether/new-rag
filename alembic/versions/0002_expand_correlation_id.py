"""§57.4 Schema 迁移 - Step 1 Expand：新增可空列（双写准备）。

Expand → Migrate → Contract 三步走，保证新旧版本短时间共存正确。
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_expand_correlation_id"
down_revision = "8486a7752a3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("correlation_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "correlation_id")
