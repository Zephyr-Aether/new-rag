"""separate release metadata from version config.

Revision ID: 0015_release_json
Revises: 0014_user_soft_delete
Create Date: 2026-08-29 00:00:00
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "0015_release_json"
down_revision = "0014_user_soft_delete"
branch_labels = None
depends_on = None


def _migrate_gray_percentage(conn, *, to_release: bool) -> None:
    rows = conn.execute(sa.text("SELECT id, config_json, release_json FROM agent_versions")).fetchall()
    for row in rows:
        cfg = json.loads(row.config_json or "{}")
        release = json.loads(getattr(row, "release_json", None) or "{}")
        changed = False
        if to_release:
            if "gray_percentage" in cfg:
                release.setdefault("gray_percentage", cfg.pop("gray_percentage"))
                changed = True
        else:
            if "gray_percentage" in release:
                cfg.setdefault("gray_percentage", release.pop("gray_percentage"))
                changed = True
        if changed:
            conn.execute(
                sa.text("UPDATE agent_versions SET config_json = :cfg, release_json = :release WHERE id = :id"),
                {"id": row.id, "cfg": json.dumps(cfg, ensure_ascii=False), "release": json.dumps(release, ensure_ascii=False)},
            )


def upgrade() -> None:
    op.add_column(
        "agent_versions",
        sa.Column("release_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
    )
    conn = op.get_bind()
    _migrate_gray_percentage(conn, to_release=True)


def downgrade() -> None:
    conn = op.get_bind()
    _migrate_gray_percentage(conn, to_release=False)
    op.drop_column("agent_versions", "release_json")
