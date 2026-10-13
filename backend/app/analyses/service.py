"""Transactional queue; no source downloads inside a database transaction.

All queue mutations lock membership before run/reservation. Attempt tokens fence
stale workers. Recovery waits beyond the child process's hard execution budget.
"""

import hashlib
import json
from datetime import timedelta
from importlib.resources import files
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.analyses.models import AnalysisRun, RunArtifact, RunEvent, SavedAnalysis
from app.analyses.schemas import ArtifactView, EventView, RunDetail, RunView
from app.plans.models import UsageReservation, WorkspacePlan
from app.plans.service import membership, reserve, settle
from app.sst.contracts import MAX_CELLS, REGIONS, AnalysisRequest
from app.sst.erddap import parse_metadata

RUN_SECONDS = 600
RECOVERY_GRACE = 30
LEASE_SECONDS = 45
MAX_ATTEMPTS = 3
TERMINAL = {"succeeded", "failed", "cancelled"}


def clock(db: Session):
    return db.scalar(select(func.clock_timestamp()))


def validate_query(query: AnalysisRequest, db: Session) -> None:
    source = parse_metadata(files("app").joinpath("data/metadata.json").read_bytes())
    if query.start < source.coverage_start or query.end >= clock(db).date():
        raise HTTPException(422, "Choose historical dates within OISST coverage (from 1981-09-01).")
    bounds = REGIONS[query.region_id].bounds
    cells = round((bounds.east - bounds.west) * (bounds.north - bounds.south) / 0.25**2)
    if cells * ((query.end - query.start).days + 1) > MAX_CELLS:
        raise HTTPException(422, "This request exceeds the 2,000,000 cell-time-value limit.")


def event(db: Session, run: AnalysisRun, stage: str, message: str) -> None:
    run.stage = stage
    db.add(
        RunEvent(
            run_id=run.id,
            attempt=run.attempt,
            stage=stage,
            message=message[:500],
            created_at=clock(db),
        )
    )


def run_view(run: AnalysisRun, moment) -> RunView:
    value = RunView.model_validate(run)
    value.results_available = bool(
        run.status == "succeeded"
        and run.expires_at
        and run.expires_at > moment
        and not run.purged_at
    )
    return value


def detail(db: Session, run: AnalysisRun) -> RunDetail:
    view = run_view(run, clock(db))
    return RunDetail(
        **view.model_dump(),
        events=[
            EventView.model_validate(row)
            for row in db.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run.id)
                .order_by(RunEvent.created_at, RunEvent.id)
                .limit(100)
            )
        ],
        artifacts=[
            ArtifactView.model_validate(row)
            for row in db.scalars(
                select(RunArtifact).where(RunArtifact.run_id == run.id).order_by(RunArtifact.name)
            )
        ]
        if view.results_available
        else [],
    )


def submit(db: Session, workspace_id: UUID, analysis_id: UUID, run_key: UUID, version: int):
    membership(db, workspace_id)
    analysis = db.scalar(
        select(SavedAnalysis)
        .where(SavedAnalysis.id == analysis_id, SavedAnalysis.workspace_id == workspace_id)
        .with_for_update()
    )
    if analysis is None:
        raise HTTPException(404, "Analysis not found.")
    existing = db.get(AnalysisRun, run_key)
    if existing:
        if (existing.workspace_id, existing.analysis_id, existing.analysis_version) != (
            workspace_id,
            analysis_id,
            version,
        ):
            raise HTTPException(409, "This run key was already used. Refresh and try again.")
        return existing
    if analysis.version != version:
        raise HTTPException(409, "The analysis changed. Refresh before starting a run.")
    query = AnalysisRequest.model_validate(analysis.query)
    validate_query(query, db)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "analysis_id": str(analysis_id),
                "version": version,
                "query": analysis.query,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    reservation = reserve(
        db,
        workspace_id,
        run_key,
        requested_days=(query.end - query.start).days + 1,
        request_hash=fingerprint,
    )
    run = AnalysisRun(
        id=run_key,
        analysis_id=analysis_id,
        workspace_id=workspace_id,
        reservation_id=reservation.id,
        title=analysis.title,
        query=analysis.query,
        analysis_version=version,
        status="queued",
        stage="queued",
        attempt=0,
        available_at=clock(db),
    )
    db.add(run)
    db.flush()
    event(db, run, "queued", "Accepted; one allowance unit reserved.")
    db.flush()
    return run


def locked_run(db: Session, run_id: UUID, workspace_id: UUID):
    membership(db, workspace_id)
    return db.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.id == run_id, AnalysisRun.workspace_id == workspace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def terminal(db: Session, run: AnalysisRun, outcome: str, message: str) -> None:
    settle(db, run.workspace_id, run.id, outcome)
    run.status = outcome
    run.finished_at = clock(db)
    run.lease_until = None
    run.error = message if outcome == "failed" else None
    reservation = db.get(UsageReservation, run.reservation_id)
    run.expires_at = run.finished_at + timedelta(days=reservation.retention_days)
    event(db, run, outcome, message)


def cancel(db: Session, run: AnalysisRun):
    run = locked_run(db, run.id, run.workspace_id)
    if run.status in TERMINAL or run.cancel_requested_at:
        return run
    run.cancel_requested_at = clock(db)
    if run.status == "queued":
        terminal(db, run, "cancelled", "Cancelled before execution; allowance released.")
    else:
        event(db, run, "cancelling", "Cancellation requested; waiting for the worker to stop.")
    db.flush()
    return run


def claim(db: Session) -> AnalysisRun | None:
    moment = clock(db)
    eligible = or_(
        and_(AnalysisRun.status == "queued", AnalysisRun.available_at <= moment),
        and_(
            AnalysisRun.status == "running",
            AnalysisRun.lease_until <= moment,
            AnalysisRun.attempt_deadline <= moment,
        ),
    )
    candidates = db.execute(
        select(AnalysisRun.id, AnalysisRun.workspace_id)
        .where(eligible)
        .order_by(AnalysisRun.created_at, AnalysisRun.id)
        .limit(100)
    ).all()
    for run_id, workspace_id in candidates:
        # Never acquire a run lock before membership: settlement uses the same order.
        member = db.scalar(
            select(WorkspacePlan)
            .where(WorkspacePlan.workspace_id == workspace_id)
            .with_for_update(skip_locked=True)
        )
        if member is None:
            continue
        run = db.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.id == run_id, eligible)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if run is None:
            continue
        if run.status == "running":
            event(
                db, run, "recovery", "Worker lost; previous attempt fenced after its time budget."
            )
        if run.cancel_requested_at:
            terminal(db, run, "cancelled", "Cancelled; allowance released.")
            continue
        if run.attempt >= MAX_ATTEMPTS:
            terminal(
                db, run, "failed", "Execution stopped after three attempts; allowance released."
            )
            continue
        run.status = "running"
        run.attempt += 1
        run.lease_token = uuid4()
        run.lease_until = moment + timedelta(seconds=LEASE_SECONDS)
        run.attempt_deadline = moment + timedelta(seconds=RUN_SECONDS + RECOVERY_GRACE)
        event(db, run, "starting", f"Starting attempt {run.attempt} of {MAX_ATTEMPTS}.")
        db.flush()
        return run
    return None


def owned_attempt(db: Session, run_id: UUID, workspace_id: UUID, token: UUID):
    run = locked_run(db, run_id, workspace_id)
    if (
        run is None
        or run.status != "running"
        or run.lease_token != token
        or run.lease_until <= clock(db)
    ):
        return None
    return run


def heartbeat(
    db: Session,
    run_id: UUID,
    workspace_id: UUID,
    token: UUID,
    progress: list[tuple[str, str]] | None = None,
):
    run = owned_attempt(db, run_id, workspace_id, token)
    if run is None:
        return "lost"
    if run.cancel_requested_at:
        return "cancel"
    for stage, message in progress or []:
        event(db, run, stage, message)
    run.lease_until = clock(db) + timedelta(seconds=LEASE_SECONDS)
    return "continue"


def finish(
    db: Session,
    run_id: UUID,
    workspace_id: UUID,
    token: UUID,
    *,
    outcome: str,
    message: str,
    artifacts: list[dict] | None = None,
    retry: bool = False,
):
    run = owned_attempt(db, run_id, workspace_id, token)
    if run is None:
        return False
    if run.cancel_requested_at:
        outcome, retry = "cancelled", False
        message = "Cancelled; allowance released."
    if retry and run.attempt < MAX_ATTEMPTS:
        run.status = "queued"
        run.available_at = clock(db) + timedelta(seconds=10 * run.attempt)
        run.lease_until = None
        event(db, run, "retrying", message + " Retrying with the same allowance reservation.")
    else:
        if outcome == "succeeded":
            if not artifacts:
                raise ValueError("Successful runs must publish verified artifacts")
            for artifact in artifacts:
                db.add(RunArtifact(run_id=run.id, **artifact))
        terminal(db, run, outcome, message)
    db.flush()
    return True
