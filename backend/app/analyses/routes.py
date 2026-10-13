from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from app.accounts.models import Workspace
from app.accounts.routes import Db, browser_write
from app.accounts.service import identity
from app.analyses import service, storage
from app.analyses.models import AnalysisRun, RunArtifact, SavedAnalysis
from app.analyses.schemas import (
    AnalysisInput,
    AnalysisUpdate,
    AnalysisView,
    RunDetail,
    RunInput,
    RunView,
)
from app.plans.service import membership
from app.sst.contracts import AnalysisResult

router = APIRouter(prefix="/api/v1", tags=["Analyses"], dependencies=[Depends(browser_write)])


def owner(request: Request, db: Db):
    user = identity(request, db).user
    return db.scalar(select(Workspace.id).where(Workspace.owner_id == user.id))


def owned_analysis(db: Db, analysis_id: UUID, workspace_id: UUID):
    analysis = db.scalar(
        select(SavedAnalysis).where(
            SavedAnalysis.id == analysis_id, SavedAnalysis.workspace_id == workspace_id
        )
    )
    if analysis is None:
        raise HTTPException(404, "Analysis not found.")
    return analysis


def owned_run(db: Db, run_id: UUID, workspace_id: UUID, *, reading: bool = False):
    statement = select(AnalysisRun).where(
        AnalysisRun.id == run_id, AnalysisRun.workspace_id == workspace_id
    )
    if reading:
        statement = statement.with_for_update(read=True)
    run = db.scalar(statement)
    if run is None:
        raise HTTPException(404, "Run not found.")
    return run


@router.get("/analyses", response_model=list[AnalysisView])
def list_analyses(request: Request, db: Db):
    return list(
        db.scalars(
            select(SavedAnalysis)
            .where(SavedAnalysis.workspace_id == owner(request, db))
            .order_by(SavedAnalysis.updated_at.desc(), SavedAnalysis.id)
            .limit(100)
        )
    )


@router.post("/analyses", response_model=AnalysisView, status_code=201)
def create_analysis(body: AnalysisInput, request: Request, db: Db):
    workspace_id = owner(request, db)
    membership(db, workspace_id)
    service.validate_query(body.query, db)
    count = db.scalar(
        select(func.count())
        .select_from(SavedAnalysis)
        .where(SavedAnalysis.workspace_id == workspace_id)
    )
    if count >= 100:
        raise HTTPException(
            409, "This workspace already has 100 saved analyses. Edit an existing analysis."
        )
    analysis = SavedAnalysis(
        workspace_id=workspace_id, title=body.title, query=body.query.model_dump(mode="json")
    )
    db.add(analysis)
    db.flush()
    return analysis


@router.patch("/analyses/{analysis_id}", response_model=AnalysisView)
def update_analysis(analysis_id: UUID, body: AnalysisUpdate, request: Request, db: Db):
    workspace_id = owner(request, db)
    membership(db, workspace_id)
    analysis = owned_analysis(db, analysis_id, workspace_id)
    if analysis.version != body.version:
        raise HTTPException(409, "The analysis changed. Refresh before editing it.")
    service.validate_query(body.query, db)
    analysis.title, analysis.query = body.title, body.query.model_dump(mode="json")
    analysis.version += 1
    analysis.updated_at = service.clock(db)
    db.flush()
    return analysis


@router.post("/analyses/{analysis_id}/runs", response_model=RunDetail, status_code=202)
def start_run(analysis_id: UUID, body: RunInput, request: Request, db: Db):
    return service.detail(
        db, service.submit(db, owner(request, db), analysis_id, body.run_key, body.version)
    )


@router.get("/analyses/{analysis_id}/runs", response_model=list[RunView])
def list_runs(
    analysis_id: UUID, request: Request, db: Db, offset: int = Query(default=0, ge=0, le=100000)
):
    workspace_id = owner(request, db)
    owned_analysis(db, analysis_id, workspace_id)
    moment = service.clock(db)
    return [
        service.run_view(run, moment)
        for run in db.scalars(
            select(AnalysisRun)
            .where(AnalysisRun.analysis_id == analysis_id, AnalysisRun.workspace_id == workspace_id)
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
            .offset(offset)
            .limit(25)
        )
    ]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: UUID, request: Request, db: Db):
    return service.detail(db, owned_run(db, run_id, owner(request, db)))


@router.post("/runs/{run_id}/cancel", response_model=RunDetail)
def cancel_run(run_id: UUID, request: Request, db: Db):
    run = owned_run(db, run_id, owner(request, db))
    return service.detail(db, service.cancel(db, run))


def downloadable_run(db: Db, run_id: UUID, workspace_id: UUID):
    run = owned_run(db, run_id, workspace_id, reading=True)
    if not service.run_view(run, service.clock(db)).results_available:
        raise HTTPException(
            410 if run.status == "succeeded" else 409,
            "Results have expired." if run.status == "succeeded" else "Results are not ready.",
        )
    return run


@router.get("/runs/{run_id}/result", response_model=AnalysisResult)
def get_result(run_id: UUID, request: Request, db: Db):
    run = downloadable_run(db, run_id, owner(request, db))
    artifact = db.scalar(
        select(RunArtifact).where(RunArtifact.run_id == run.id, RunArtifact.name == "analysis.json")
    )
    if artifact is None:
        raise HTTPException(503, "Result manifest is unavailable.")
    return AnalysisResult.model_validate_json(storage.read_artifact(artifact))


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
def download(run_id: UUID, artifact_id: UUID, request: Request, db: Db):
    run = downloadable_run(db, run_id, owner(request, db))
    artifact = db.scalar(
        select(RunArtifact).where(RunArtifact.id == artifact_id, RunArtifact.run_id == run.id)
    )
    if artifact is None:
        raise HTTPException(404, "Artifact not found.")
    return Response(
        storage.read_artifact(artifact),
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.name}"'},
    )
