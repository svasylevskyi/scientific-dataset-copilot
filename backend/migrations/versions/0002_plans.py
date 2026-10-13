"""Managed free plans, workspace assignments, usage reservations and expense ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0002_plans"
down_revision = "0001_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("monthly_analyses", sa.Integer(), nullable=False),
        sa.Column("concurrent_analyses", sa.Integer(), nullable=False),
        sa.Column("max_date_range_days", sa.Integer(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("concurrent_analyses BETWEEN 1 AND 20", name="plan_concurrent_analyses"),
        sa.CheckConstraint("max_date_range_days BETWEEN 1 AND 3663", name="plan_date_range"),
        sa.CheckConstraint("monthly_analyses BETWEEN 0 AND 10000", name="plan_monthly_analyses"),
        sa.CheckConstraint("retention_days BETWEEN 1 AND 3650", name="plan_retention"),
        sa.CheckConstraint("version >= 1", name="plan_version"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "plan_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_plan_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("id = 1", name="plan_settings_singleton"),
        sa.ForeignKeyConstraint(["default_plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workspace_plans",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="workspace_plan_status"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_index(
        op.f("ix_workspace_plans_plan_id"), "workspace_plans", ["plan_id"], unique=False
    )
    op.create_table(
        "usage_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("run_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("requested_days", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=10), nullable=True),
        sa.CheckConstraint(
            "(status = 'released' AND release_reason IS NOT NULL "
            "AND release_reason IN ('failed', 'cancelled')) OR "
            "(status <> 'released' AND release_reason IS NULL)",
            name="usage_release_reason",
        ),
        sa.CheckConstraint(
            "(status = 'reserved' AND finished_at IS NULL) OR "
            "(status <> 'reserved' AND finished_at IS NOT NULL)",
            name="usage_finished",
        ),
        sa.CheckConstraint("status IN ('reserved', 'consumed', 'released')", name="usage_status"),
        sa.CheckConstraint("requested_days BETWEEN 1 AND 3663", name="usage_requested_days"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "run_key", name="usage_workspace_run"),
    )
    op.create_index(
        "ix_usage_workspace_period_status",
        "usage_reservations",
        ["workspace_id", "period_start", "status"],
        unique=False,
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=10), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('reserved', 'consumed', 'released')", name="usage_event_kind"),
        sa.ForeignKeyConstraint(["reservation_id"], ["usage_reservations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reservation_id", "kind", name="usage_event_once"),
    )
    op.create_table(
        "processing_costs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("amount_usd", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_usd >= 0", name="processing_cost_nonnegative"),
        sa.ForeignKeyConstraint(["reservation_id"], ["usage_reservations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reservation_id", "event_key", name="processing_cost_once"),
    )

    op.execute("""
        INSERT INTO plans (id, name, description, active, monthly_analyses,
                           concurrent_analyses, max_date_range_days, retention_days, version)
        VALUES ('e9b70a10-7b56-4f3e-8af7-a5d6f693b111', 'Development',
                'Free access for development and testing.', true, 20, 1, 3663, 30, 1)
    """)
    op.execute("""
        INSERT INTO plan_settings (id, default_plan_id)
        VALUES (1, 'e9b70a10-7b56-4f3e-8af7-a5d6f693b111')
    """)
    op.execute("""
        INSERT INTO workspace_plans (workspace_id, plan_id, status)
        SELECT id, 'e9b70a10-7b56-4f3e-8af7-a5d6f693b111', 'active' FROM workspaces
    """)


def downgrade():
    op.drop_table("processing_costs")
    op.drop_table("usage_events")
    op.drop_table("usage_reservations")
    op.drop_table("workspace_plans")
    op.drop_table("plan_settings")
    op.drop_table("plans")
