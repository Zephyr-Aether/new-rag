"""§57.4 Schema 迁移 - Release Ops：补齐 release/cost/queue/events 演进引入的表与列。

- regression_runs 表（§20 评测回归）
- events 表（§28.2 事件 Outbox）
- chunks.shard 列（§24 租户分区）
- jobs.dedupe_key 列（§11 队列单飞）
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_release_ops"
down_revision = "0004_contract_correlation_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regression_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("agent_version", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=False),
        sa.Column("regressed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_regression_runs_agent_id"), "regression_runs", ["agent_id"], unique=False)
    op.create_index(op.f("ix_regression_runs_tenant_id"), "regression_runs", ["tenant_id"], unique=False)
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(op.f("ix_events_event_type"), "events", ["event_type"], unique=False)
    op.create_index(op.f("ix_events_tenant_id"), "events", ["tenant_id"], unique=False)
    # §24 租户分区：存量块回落 shard=0（shard_count=1 时语义不变）
    op.add_column(
        "chunks",
        sa.Column("shard", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(op.f("ix_chunks_shard"), "chunks", ["shard"], unique=False)
    # §11 队列单飞
    op.add_column("jobs", sa.Column("dedupe_key", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_jobs_dedupe_key"), "jobs", ["dedupe_key"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_dedupe_key"), table_name="jobs")
    op.drop_column("jobs", "dedupe_key")
    op.drop_index(op.f("ix_chunks_shard"), table_name="chunks")
    op.drop_column("chunks", "shard")
    op.drop_index(op.f("ix_events_tenant_id"), table_name="events")
    op.drop_index(op.f("ix_events_event_type"), table_name="events")
    op.drop_table("events")
    op.drop_index(op.f("ix_regression_runs_tenant_id"), table_name="regression_runs")
    op.drop_index(op.f("ix_regression_runs_agent_id"), table_name="regression_runs")
    op.drop_table("regression_runs")
