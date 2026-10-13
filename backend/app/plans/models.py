from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("monthly_analyses BETWEEN 0 AND 10000", name="plan_monthly_analyses"),
        CheckConstraint("concurrent_analyses BETWEEN 1 AND 20", name="plan_concurrent_analyses"),
        CheckConstraint("max_date_range_days BETWEEN 1 AND 3663", name="plan_date_range"),
        CheckConstraint("retention_days BETWEEN 1 AND 3650", name="plan_retention"),
        CheckConstraint("version >= 1", name="plan_version"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_analyses: Mapped[int] = mapped_column(Integer)
    concurrent_analyses: Mapped[int] = mapped_column(Integer)
    max_date_range_days: Mapped[int] = mapped_column(Integer)
    retention_days: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanSettings(Base):
    __tablename__ = "plan_settings"
    __table_args__ = (CheckConstraint("id = 1", name="plan_settings_singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    default_plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))


class WorkspacePlan(Base):
    __tablename__ = "workspace_plans"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="workspace_plan_status"),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="active")
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UsageReservation(Base):
    __tablename__ = "usage_reservations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "run_key", name="usage_workspace_run"),
        CheckConstraint("status IN ('reserved', 'consumed', 'released')", name="usage_status"),
        CheckConstraint("requested_days BETWEEN 1 AND 3663", name="usage_requested_days"),
        CheckConstraint(
            "(status = 'reserved' AND finished_at IS NULL) OR "
            "(status <> 'reserved' AND finished_at IS NOT NULL)",
            name="usage_finished",
        ),
        CheckConstraint(
            "(status = 'released' AND release_reason IS NOT NULL "
            "AND release_reason IN ('failed', 'cancelled')) OR "
            "(status <> 'released' AND release_reason IS NULL)",
            name="usage_release_reason",
        ),
        Index("ix_usage_workspace_period_status", "workspace_id", "period_start", "status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    run_key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="reserved")
    requested_days: Mapped[int] = mapped_column(Integer)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))
    plan_version: Mapped[int] = mapped_column(Integer)
    # Retention is fixed at reservation, so later plan edits cannot shorten a run's promise.
    retention_days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(10))


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("reservation_id", "kind", name="usage_event_once"),
        CheckConstraint("kind IN ('reserved', 'consumed', 'released')", name="usage_event_kind"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("usage_reservations.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessingCost(Base):
    __tablename__ = "processing_costs"
    __table_args__ = (
        UniqueConstraint("reservation_id", "event_key", name="processing_cost_once"),
        CheckConstraint("amount_usd >= 0", name="processing_cost_nonnegative"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("usage_reservations.id", ondelete="CASCADE")
    )
    event_key: Mapped[UUID] = mapped_column()
    category: Mapped[str] = mapped_column(String(60))
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
