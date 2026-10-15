import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.accounts.rate_limit import consume
from app.accounts.routes import Db, browser_write
from app.analyses.routes import owner
from app.analyses.schemas import AnalysisInput, AnalysisView
from app.copilot import provider, service
from app.copilot.config import config
from app.copilot.schemas import PlannerStatus, PlanningCosts, PlanningInput, PlanningView, Proposal
from app.db import engine
from app.plans.routes import administrator

router = APIRouter(prefix="/api/v1", tags=["Copilot"], dependencies=[Depends(browser_write)])


@router.get("/copilot/status", response_model=PlannerStatus)
def planner_status(request: Request, db: Db):
    return service.status(db, owner(request, db), config())


@router.post("/copilot/requests", response_model=PlanningView)
def plan(body: PlanningInput, request: Request):
    cfg = config()
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        workspace_id = owner(request, db)
        consume(f"copilot:{workspace_id}", 6, 60)
        row, outbound = service.admit(db, workspace_id, body, cfg)
        if outbound is None:
            return service.view(row)
        key = row.id
    result = asyncio.run(provider.extract(outbound, cfg.key))
    with Session(engine()) as db, db.begin():
        service.finish(db, key, result)
    # Recheck the session after network I/O, while still retaining provider accounting.
    with Session(engine()) as db, db.begin():
        return service.view(service.owned(db, key, owner(request, db)))


@router.get("/copilot/requests/{key}", response_model=PlanningView)
def get_plan(key: UUID, request: Request, db: Db):
    return service.view(service.owned(db, key, owner(request, db)))


@router.post("/copilot/preview", response_model=Proposal)
def preview(body: AnalysisInput, request: Request, db: Db):
    return service.preview(db, owner(request, db), body)


@router.post("/copilot/requests/{key}/accept", response_model=AnalysisView)
def accept(key: UUID, body: AnalysisInput, request: Request, db: Db):
    return service.accept(db, owner(request, db), key, body)


@router.get(
    "/admin/copilot/usage", response_model=PlanningCosts, dependencies=[Depends(administrator)]
)
def cost_summary(db: Db):
    return service.costs(db, config())
