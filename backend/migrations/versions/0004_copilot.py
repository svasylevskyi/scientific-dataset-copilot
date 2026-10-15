"""Private planning proposals and independent AI usage/cost reservations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_copilot"
down_revision = "0003_analyses"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planning_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("transcript", postgresql.JSONB(), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("proposal", postgresql.JSONB(), nullable=True),
        sa.Column("analysis_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_hash", sa.String(64), nullable=True),
        sa.Column("budget_day", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("pricing_version", sa.String(50), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(14, 6), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'clarification', 'unsupported', 'failed')",
            name="planning_status",
        ),
        sa.CheckConstraint("turn BETWEEN 1 AND 3", name="planning_turn"),
        sa.CheckConstraint("reserved_usd >= 0 AND estimated_cost_usd >= 0", name="planning_cost"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_planning_day_owner", "planning_requests", ["budget_day", "workspace_id"])


def downgrade():
    op.drop_table("planning_requests")
