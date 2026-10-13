from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from app.accounts.models import User, Workspace
from app.accounts.routes import Db, browser_write
from app.accounts.schemas import Message
from app.accounts.security import now
from app.accounts.service import identity
from app.plans.models import Plan, WorkspacePlan
from app.plans.schemas import (
    AdminPlanView,
    AssignmentInput,
    PlanInput,
    PlanUpdate,
    PlanVersion,
    PlanView,
    UsageView,
)
from app.plans.service import catalogue, get_plan, membership, plan_view, usage_view

router = APIRouter(prefix="/api/v1", tags=["Plans"], dependencies=[Depends(browser_write)])


def administrator(request: Request, db: Db):
    if identity(request, db).user.role != "admin":
        raise HTTPException(403, "Administrator access is required.")


def assert_version(plan: Plan, version: int):
    if plan.version != version:
        raise HTTPException(409, "This plan changed since you opened it. Refresh and try again.")


def assert_name_available(db: Db, name: str, exclude: UUID | None = None):
    statement = select(Plan.id).where(func.lower(Plan.name) == name.lower())
    if exclude is not None:
        statement = statement.where(Plan.id != exclude)
    if db.scalar(statement):
        raise HTTPException(409, "A plan with this name already exists.")


@router.get("/account/usage", response_model=UsageView)
def account_usage(request: Request, db: Db):
    user = identity(request, db).user
    workspace_id = db.scalar(select(Workspace.id).where(Workspace.owner_id == user.id))
    return usage_view(db, workspace_id)


@router.get(
    "/admin/plans", response_model=list[AdminPlanView], dependencies=[Depends(administrator)]
)
def list_plans(db: Db):
    config = catalogue(db)
    counts = dict(
        db.execute(
            select(WorkspacePlan.plan_id, func.count()).group_by(WorkspacePlan.plan_id)
        ).all()
    )
    return [
        AdminPlanView(
            **plan_view(plan, config.default_plan_id).model_dump(),
            workspace_count=counts.get(plan.id, 0),
        )
        for plan in db.scalars(select(Plan).order_by(Plan.created_at, Plan.id))
    ]


@router.post(
    "/admin/plans", response_model=PlanView, status_code=201, dependencies=[Depends(administrator)]
)
def create_plan(body: PlanInput, db: Db):
    config = catalogue(db, write=True)
    assert_name_available(db, body.name)
    plan = Plan(**body.model_dump())
    db.add(plan)
    db.flush()
    return plan_view(plan, config.default_plan_id)


@router.patch(
    "/admin/plans/{plan_id}", response_model=PlanView, dependencies=[Depends(administrator)]
)
def update_plan(plan_id: UUID, body: PlanUpdate, db: Db):
    config = catalogue(db, write=True)
    plan = get_plan(db, plan_id, write=True)
    assert_version(plan, body.version)
    if plan_id == config.default_plan_id and not body.active:
        raise HTTPException(409, "Choose another default plan before archiving this one.")
    assert_name_available(db, body.name, plan_id)
    for field, value in body.model_dump(exclude={"version"}).items():
        setattr(plan, field, value)
    plan.version += 1
    db.flush()
    return plan_view(plan, config.default_plan_id)


@router.post(
    "/admin/plans/{plan_id}/default", response_model=PlanView, dependencies=[Depends(administrator)]
)
def default_plan(plan_id: UUID, body: PlanVersion, db: Db):
    config = catalogue(db, write=True)
    plan = get_plan(db, plan_id)
    assert_version(plan, body.version)
    if not plan.active:
        raise HTTPException(409, "Activate this plan before making it the default.")
    config.default_plan_id = plan.id
    db.flush()
    return plan_view(plan, config.default_plan_id)


@router.post(
    "/admin/plan-assignments", response_model=Message, dependencies=[Depends(administrator)]
)
def assign_plan(body: AssignmentInput, db: Db):
    catalogue(db, write=True)
    workspace_id = db.scalar(
        select(Workspace.id)
        .join(User, User.id == Workspace.owner_id)
        .where(User.email == body.email)
    )
    if workspace_id is None:
        raise HTTPException(404, "No account with that email was found.")
    subscription = membership(db, workspace_id)
    plan = get_plan(db, body.plan_id)
    if not plan.active:
        raise HTTPException(409, "Activate this plan before assigning it.")
    subscription.plan_id = plan.id
    subscription.status = body.status
    subscription.assigned_at = now()
    return Message(
        message="Plan assignment saved. Existing usage and running reservations are retained."
    )
