"""§H.1 CostBreakdown：llm_calls 加 prompt/history/tool/rag 分项 token 列。"""

import sqlalchemy as sa

from alembic import op

revision = "0007_llm_token_breakdown"
down_revision = "a89bccbd6b84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False))
    op.add_column("llm_calls", sa.Column("history_tokens", sa.Integer(), server_default="0", nullable=False))
    op.add_column("llm_calls", sa.Column("tool_tokens", sa.Integer(), server_default="0", nullable=False))
    op.add_column("llm_calls", sa.Column("rag_tokens", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("llm_calls", "rag_tokens")
    op.drop_column("llm_calls", "tool_tokens")
    op.drop_column("llm_calls", "history_tokens")
    op.drop_column("llm_calls", "prompt_tokens")
