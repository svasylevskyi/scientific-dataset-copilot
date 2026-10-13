"""All mutations share the caller's transaction; no dispatch or external I/O here.

Lock order: catalogue settings -> membership -> plan -> reservation. Catalogue
operations may skip membership. Reservations skip settings. Read locks on plans
serialize policy changes with admission, without serializing different workspaces.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.models import Workspace
from app.accounts.security import now
from app.plans.models import (
    Plan,
    PlanSettings,
    ProcessingCost,
    UsageEvent,
    UsageReservation,
    WorkspacePlan,
)
from app.plans.schemas import PlanView, UsageRecord, UsageView


def month_bounds(moment: datetime) -> tuple[date, date]:
    if moment.tzinfo is None:
        raise ValueError("Usage timestamps must include a timezone")
    start = moment.astimezone(UTC).date().replace(day=1)
    end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    return start, end


def catalogue(db: Session, *, write: bool = False) -> PlanSettings:
    result = db.scalar(
        select(PlanSettings)
        .where(PlanSettings.id == 1)
        .with_for_update(read=not write)
        .execution_options(populate_existing=True)
    )
    if result is None:
        raise HTTPException(503, "Plan configuration is unavailable. Please try again shortly.")
    return result


def get_plan(db: Session, plan_id: UUID, *, write: bool = False) -> Plan:
    plan = db.scalar(
        select(Plan)
        .where(Plan.id == plan_id)
        .with_for_update(read=not write)
        .execution_options(populate_existing=True)
    )
    if plan is None:
        raise HTTPException(404, "Plan not found.")
    return plan


def assign_default(db: Session, workspace: Workspace) -> None:
    config = catalogue(db)
    plan = get_plan(db, config.default_plan_id)
    if not plan.active:
        raise HTTPException(503, "The default plan is unavailable. Please try again shortly.")
    db.flush()
    db.add(WorkspacePlan(workspace_id=workspace.id, plan_id=plan.id, status="active"))


def membership(db: Session, workspace_id: UUID) -> WorkspacePlan:
    result = db.scalar(
        select(WorkspacePlan)
        .where(WorkspacePlan.workspace_id == workspace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if result is None:
        raise HTTPException(403, "This workspace has no assigned plan. Contact an administrator.")
    return result


def plan_view(plan: Plan, default_id: UUID) -> PlanView:
    values = {
        name: getattr(plan, name)
        for name in (
            "id",
            "name",
            "description",
            "active",
            "monthly_analyses",
            "concurrent_analyses",
            "max_date_range_days",
            "retention_days",
            "version",
        )
    }
    return PlanView(**values, is_default=plan.id == default_id)


def counts(db: Session, workspace_id: UUID, start: date) -> tuple[int, int, int]:
    current = UsageReservation.period_start == start
    consumed, reserved, concurrent = db.execute(
        select(
            func.count().filter(current, UsageReservation.status == "consumed"),
            func.count().filter(current, UsageReservation.status == "reserved"),
            func.count().filter(UsageReservation.status == "reserved"),
        ).where(UsageReservation.workspace_id == workspace_id)
    ).one()
    return consumed, reserved, concurrent


def blocked(plan: Plan, status: str, consumed: int, reserved: int, concurrent: int) -> str | None:
    if status != "active":
        return "Analysis access is suspended. Contact an administrator."
    if consumed + reserved >= plan.monthly_analyses:
        return "Your monthly analysis allowance is fully used or reserved."
    if concurrent >= plan.concurrent_analyses:
        return "Your simultaneous analysis limit is reached. Wait for an active run to finish."
    return None


def usage_view(db: Session, workspace_id: UUID) -> UsageView:
    # Take the catalogue read lock first, consistent with admin assignments.
    config = catalogue(db)
    subscription = membership(db, workspace_id)
    plan = get_plan(db, subscription.plan_id)
    start, end = month_bounds(now())
    consumed, reserved, concurrent = counts(db, workspace_id, start)
    reason = blocked(plan, subscription.status, consumed, reserved, concurrent)
    recent = db.scalars(
        select(UsageReservation)
        .where(UsageReservation.workspace_id == workspace_id)
        .order_by(UsageReservation.created_at.desc(), UsageReservation.id.desc())
        .limit(20)
    )
    return UsageView(
        plan=plan_view(plan, config.default_plan_id),
        status=subscription.status,
        period_start=start,
        period_end=end,
        consumed=consumed,
        reserved=reserved,
        remaining=max(0, plan.monthly_analyses - consumed - reserved),
        concurrent_reserved=concurrent,
        can_reserve=reason is None,
        blocked_reason=reason,
        recent=[UsageRecord.model_validate(row) for row in recent],
    )


def reserve(
    db: Session,
    workspace_id: UUID,
    run_key: UUID,
    *,
    requested_days: int,
    request_hash: str,
) -> UsageReservation:
    """Internal admission API. Call only after authorization and validated query planning.

    One immutable run key = one unit. A retry returns the existing state; callers
    must never dispatch a consumed/released reservation as a new run. Reserve and
    persist the future job/outbox atomically before dispatch in increment 4.
    """
    if (
        type(requested_days) is not int
        or not 1 <= requested_days <= 3663
        or len(request_hash) != 64
        or any(c not in "0123456789abcdef" for c in request_hash)
    ):
        raise ValueError("A validated date span and SHA-256 request fingerprint are required")
    subscription = membership(db, workspace_id)
    existing = db.scalar(
        select(UsageReservation)
        .where(UsageReservation.workspace_id == workspace_id, UsageReservation.run_key == run_key)
        .execution_options(populate_existing=True)
    )
    if existing:
        if existing.requested_days != requested_days or existing.request_hash != request_hash:
            raise HTTPException(409, "This run key was already used for a different request.")
        return existing
    plan = get_plan(db, subscription.plan_id)
    if type(requested_days) is not int or not 1 <= requested_days <= plan.max_date_range_days:
        raise HTTPException(
            403, f"This plan allows at most {plan.max_date_range_days} days per analysis."
        )
    moment = now()
    start, _ = month_bounds(moment)
    reason = blocked(plan, subscription.status, *counts(db, workspace_id, start))
    if reason:
        raise HTTPException(403, reason)
    reservation = UsageReservation(
        workspace_id=workspace_id,
        run_key=run_key,
        request_hash=request_hash,
        period_start=start,
        requested_days=requested_days,
        plan_id=plan.id,
        plan_version=plan.version,
        retention_days=plan.retention_days,
        created_at=moment,
        status="reserved",
    )
    db.add(reservation)
    db.flush()
    db.add(UsageEvent(reservation_id=reservation.id, kind="reserved", created_at=moment))
    db.flush()
    return reservation


def settle(
    db: Session,
    workspace_id: UUID,
    run_key: UUID,
    outcome: Literal["succeeded", "failed", "cancelled"],
) -> UsageReservation:
    """Release only after the worker confirms terminal failure/cancellation.

    No automatic time-based release: a slow or disconnected worker may still be
    running. Cross-month completion always settles against the admission month.
    """
    if outcome not in {"succeeded", "failed", "cancelled"}:
        raise ValueError("Unknown analysis outcome")
    membership(db, workspace_id)
    reservation = db.scalar(
        select(UsageReservation)
        .where(UsageReservation.workspace_id == workspace_id, UsageReservation.run_key == run_key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if reservation is None:
        raise HTTPException(404, "Analysis reservation not found.")
    status = "consumed" if outcome == "succeeded" else "released"
    reason = None if outcome == "succeeded" else outcome
    if reservation.status != "reserved":
        if reservation.status != status or reservation.release_reason != reason:
            raise HTTPException(409, "This analysis already has a different final outcome.")
        return reservation
    reservation.status = status
    reservation.release_reason = reason
    reservation.finished_at = now()
    db.add(
        UsageEvent(
            reservation_id=reservation.id,
            kind=status,
            reason=reason,
            created_at=reservation.finished_at,
        )
    )
    db.flush()
    return reservation


def record_cost(
    db: Session,
    reservation_id: UUID,
    event_key: UUID,
    *,
    category: str,
    amount_usd: Decimal,
) -> ProcessingCost:
    """Internal, idempotent expense ledger, independent of customer quota outcomes."""
    if (
        not amount_usd.is_finite()
        or not 0 <= amount_usd < Decimal("100000000")
        or amount_usd != amount_usd.quantize(Decimal("0.000001"))
        or not category.strip()
        or len(category) > 60
    ):
        raise ValueError("Invalid processing cost")
    workspace_id = db.scalar(
        select(UsageReservation.workspace_id).where(UsageReservation.id == reservation_id)
    )
    if workspace_id is None:
        raise HTTPException(404, "Analysis reservation not found.")
    membership(db, workspace_id)
    reservation = db.scalar(
        select(UsageReservation).where(UsageReservation.id == reservation_id).with_for_update()
    )
    if reservation is None:
        raise HTTPException(404, "Analysis reservation not found.")
    existing = db.scalar(
        select(ProcessingCost).where(
            ProcessingCost.reservation_id == reservation_id, ProcessingCost.event_key == event_key
        )
    )
    if existing:
        if existing.category != category or existing.amount_usd != amount_usd:
            raise HTTPException(409, "This cost event was already recorded with different values.")
        return existing
    cost = ProcessingCost(
        reservation_id=reservation_id, event_key=event_key, category=category, amount_usd=amount_usd
    )
    db.add(cost)
    db.flush()
    return cost
