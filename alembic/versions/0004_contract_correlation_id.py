"""§57.4 Schema 迁移 - Step 3 Contract：回填完成后收紧为 NOT NULL（双写清理后可删旧列）。

SQLite 经 render_as_batch=True 以表重建方式支持 alter_column；PG 原生 ALTER。
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_contract_correlation_id"
down_revision = "0003_backfill_correlation_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("audit_logs", "correlation_id", existing_type=sa.String(length=64), nullable=False)


def downgrade() -> None:
    op.alter_column("audit_logs", "correlation_id", existing_type=sa.String(length=64), nullable=True)
