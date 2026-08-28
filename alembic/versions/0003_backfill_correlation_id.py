"""§57.4 Schema 迁移 - Step 2 Migrate：后台回填新列（幂等）。

Expand 后旧版本不写新列，本步补齐存量数据。
"""

from alembic import op

revision = "0003_backfill_correlation_id"
down_revision = "0002_expand_correlation_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE audit_logs SET correlation_id = id WHERE correlation_id IS NULL")


def downgrade() -> None:
    pass
