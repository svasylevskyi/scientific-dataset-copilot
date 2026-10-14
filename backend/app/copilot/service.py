"""Short admission/settlement transactions surround, never span, the provider call."""

import hashlib
import json
from datetime import UTC, date, timedelta
from importlib.resources import files
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.analyses.models import SavedAnalysis
from app.analyses.schemas import AnalysisInput
from app.analyses.service import clock as database_clock
from app.analyses.service import validate_query
from app.copilot import provider
from app.copilot.config import MAX_TURNS, MODEL, PRICING_VERSION, PROMPT_VERSION, CopilotConfig
from app.copilot.models import PlanningRequest
from app.copilot.schemas import (
    Intent,
    PlannerStatus,
    PlanningCosts,
    PlanningInput,
    PlanningView,
    Proposal,
)
from app.plans.service import membership, usage_view
from app.sst.contracts import REGIONS, AnalysisRequest
from app.sst.erddap import SourceError, plan_query

UNSUPPORTED = (
    "This planner supports monthly sea surface temperature in °C for one region: "
    "the Canary Islands or Madeira, using NOAA OISST. Please request that workflow "
    "or use the manual form. Other variables, regions and calculations are not available yet."
)
FAILED = "Planning could not be completed. Try a new request or use the manual form."
QUESTIONS = {
    "variable": "Do you mean sea surface temperature? Other temperatures are not supported.",
    "region": "Which surrounding-ocean region: the Canary Islands or Madeira?",
    "dates": "Which dates should be included? Use a year or an explicit start and end date.",
    "method": "Would you like area-weighted monthly sea surface temperature in °C?",
    "ambiguous": "Please clarify the variable, region and dates without ambiguous date formats.",
}


def clock(db: Session):
    return database_clock(db).astimezone(UTC)


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def budget_lock(db: Session):
    # All budget admissions and settlements take this same transaction-scoped lock.
    db.execute(text("SELECT pg_advisory_xact_lock(1935960901)"))


def costs(db: Session, cfg: CopilotConfig, day: date | None = None) -> PlanningCosts:
    day = day or clock(db).date()
    count, estimated, unresolved, used = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(PlanningRequest.estimated_cost_usd), 0),
            func.count().filter(PlanningRequest.estimated_cost_usd.is_(None)),
            func.coalesce(
                func.sum(
                    func.coalesce(PlanningRequest.estimated_cost_usd, PlanningRequest.reserved_usd)
                ),
                0,
            ),
        ).where(PlanningRequest.budget_day == day)
    ).one()
    return PlanningCosts(
        day=day,
        model=MODEL,
        requests=count,
        estimated_cost_usd=estimated,
        unresolved_requests=unresolved,
        budget_used_usd=used,
        daily_budget_usd=cfg.daily_budget_usd,
    )


def status(db: Session, workspace_id: UUID, cfg: CopilotConfig) -> PlannerStatus:
    moment = clock(db)
    used = db.scalar(
        select(func.count())
        .select_from(PlanningRequest)
        .where(
            PlanningRequest.workspace_id == workspace_id,
            PlanningRequest.budget_day == moment.date(),
        )
    )
    member = membership(db, workspace_id)
    reason = None
    if not cfg.enabled:
        reason = (
            "Guided planning is not configured. You can create an analysis with the manual form."
        )
    elif member.status != "active":
        reason = "Analysis access is suspended. Contact an administrator."
    elif used >= cfg.daily_requests:
        reason = (
            "Your daily planning limit is reached. Use the manual form or return after the reset."
        )
    elif costs(db, cfg).budget_used_usd >= cfg.daily_budget_usd:
        reason = (
            "Guided planning has reached its daily service budget. The manual form is available."
        )
    return PlannerStatus(
        enabled=cfg.enabled,
        daily_limit=cfg.daily_requests,
        remaining=max(0, cfg.daily_requests - used),
        resets_at=(moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0),
        blocked_reason=reason,
    )


def owned(db: Session, key: UUID, workspace_id: UUID) -> PlanningRequest:
    row = db.scalar(
        select(PlanningRequest)
        .where(PlanningRequest.id == key, PlanningRequest.workspace_id == workspace_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Planning request not found.")
    expire(db, row)
    return row


def expire(db: Session, row: PlanningRequest):
    if row.status == "pending" and clock(db) > row.created_at + timedelta(seconds=120):
        row.status, row.message, row.finished_at = "failed", FAILED, clock(db)
        # Keep the full reservation when usage is unknown. Never retry a paid call implicitly.


def view(row: PlanningRequest) -> PlanningView:
    return PlanningView(
        id=row.id,
        status=row.status,
        message=row.message,
        prompt=row.transcript[-1]["content"],
        turn=row.turn,
        proposal=row.proposal,
        analysis_id=row.analysis_id,
        created_at=row.created_at,
    )


def admit(db: Session, workspace_id: UUID, body: PlanningInput, cfg: CopilotConfig):
    member = membership(db, workspace_id)
    digest = fingerprint(body.model_dump(mode="json"))
    existing = db.get(PlanningRequest, body.request_key)
    if existing:
        if existing.workspace_id != workspace_id or existing.request_hash != digest:
            raise HTTPException(409, "This planning key was already used. Start a new request.")
        expire(db, existing)
        return existing, None
    availability = status(db, workspace_id, cfg)
    if availability.blocked_reason:
        raise HTTPException(
            503 if not cfg.enabled else 403 if member.status != "active" else 429,
            availability.blocked_reason,
        )
    transcript = []
    turn = 1
    if body.parent_id:
        parent = owned(db, body.parent_id, workspace_id)
        if parent.status != "clarification" or parent.turn >= MAX_TURNS:
            raise HTTPException(409, "Start a new request or use the manual form.")
        transcript = parent.transcript + [{"role": "assistant", "content": parent.message}]
        turn = parent.turn + 1
    # Serialize per-workspace calls without holding a lock during network I/O.
    for pending in db.scalars(
        select(PlanningRequest)
        .where(PlanningRequest.workspace_id == workspace_id, PlanningRequest.status == "pending")
        .with_for_update()
    ):
        expire(db, pending)
        if pending.status == "pending":
            raise HTTPException(
                409, "Another planning request is still processing. Refresh its status."
            )
    transcript.append({"role": "user", "content": body.prompt})
    moment = clock(db)
    outbound = provider.payload(transcript, moment.date())
    reserve = provider.reservation(outbound)
    budget_lock(db)
    if costs(db, cfg, moment.date()).budget_used_usd + reserve > cfg.daily_budget_usd:
        raise HTTPException(
            429, "The daily planning budget cannot cover another request. Use the manual form."
        )
    row = PlanningRequest(
        id=body.request_key,
        workspace_id=workspace_id,
        request_hash=digest,
        transcript=transcript,
        turn=turn,
        status="pending",
        message="Preparing your proposal…",
        budget_day=moment.date(),
        created_at=moment,
        model=MODEL,
        prompt_version=PROMPT_VERSION,
        pricing_version=PRICING_VERSION,
        reserved_usd=reserve,
    )
    db.add(row)
    db.flush()
    return row, outbound


def preview(db: Session, workspace_id: UUID, analysis: AnalysisInput) -> Proposal:
    validate_query(analysis.query, db)
    usage = usage_view(db, workspace_id)
    if (analysis.query.end - analysis.query.start).days + 1 > usage.plan.max_date_range_days:
        raise HTTPException(
            422, f"Your plan allows at most {usage.plan.max_date_range_days} days per analysis."
        )
    raw = files("app").joinpath("data/metadata.json").read_bytes()
    saved = json.loads(files("app").joinpath("data/reference.json").read_text())
    try:
        plan = plan_query(analysis.query, raw, saved["plan"]["metadata_fetched_at"])
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Proposal(
        analysis=analysis,
        plan=plan,
        retention_days=usage.plan.retention_days,
        can_run=usage.can_reserve,
        blocked_reason=usage.blocked_reason,
    )


def interpret(db: Session, workspace_id: UUID, intent: Intent):
    if intent.operation == "unsupported":
        return "unsupported", UNSUPPORTED, None
    questions = []
    if intent.clarification != "none":
        questions.append(QUESTIONS[intent.clarification])
    if intent.operation == "unclear" and not questions:
        questions.append(QUESTIONS["ambiguous"])
    if intent.region_id is None and QUESTIONS["region"] not in questions:
        questions.append(QUESTIONS["region"])
    if (intent.start is None or intent.end is None) and QUESTIONS["dates"] not in questions:
        questions.append(QUESTIONS["dates"])
    if questions:
        return "clarification", " ".join(questions), None
    try:
        query = AnalysisRequest(region_id=intent.region_id, start=intent.start, end=intent.end)
        title = f"{REGIONS[query.region_id].name.split(' —')[0]} SST · {query.start} to {query.end}"
        proposal = preview(db, workspace_id, AnalysisInput(title=title, query=query))
    except ValidationError:
        return "clarification", "Please choose an ordered date range of at most 3,663 days.", None
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return "clarification", str(exc.detail), None
    return "ready", "Review the proposed region, dates and method before saving.", proposal


def finish(db: Session, key: UUID, result: provider.ProviderResult):
    # Take membership/catalogue locks before the global budget lock, as admission does.
    row = db.get(PlanningRequest, key)
    proposal = None
    state, message = "failed", FAILED
    if result.intent:
        try:
            state, message, proposal = interpret(db, row.workspace_id, result.intent)
        except HTTPException:
            pass  # Access may have changed during the provider call; preserve its cost.
    budget_lock(db)
    row = db.scalar(
        select(PlanningRequest)
        .where(PlanningRequest.id == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.input_tokens is not None:
        return  # Settlement is idempotent.
    row.input_tokens, row.cached_tokens, row.output_tokens = (
        result.input_tokens,
        result.cached_tokens,
        result.output_tokens,
    )
    row.estimated_cost_usd = result.cost
    if row.status == "pending":
        row.status, row.message = state, message[:500]
        row.proposal = proposal.model_dump(mode="json") if proposal else None
        row.finished_at = clock(db)


def accept(db: Session, workspace_id: UUID, key: UUID, body: AnalysisInput) -> SavedAnalysis:
    # Match the catalogue -> membership order used by normal usage/plan mutations.
    checked = preview(db, workspace_id, body)
    if checked.blocked_reason and membership(db, workspace_id).status != "active":
        raise HTTPException(403, checked.blocked_reason)
    row = owned(db, key, workspace_id)
    digest = fingerprint(body.model_dump(mode="json"))
    if row.analysis_id:
        if row.accepted_hash != digest:
            raise HTTPException(
                409, "This proposal was already saved. Edit the saved analysis instead."
            )
        return db.get(SavedAnalysis, row.analysis_id)
    if row.status != "ready":
        raise HTTPException(409, "Only a ready proposal can be saved. Use the manual form instead.")
    count = db.scalar(
        select(func.count())
        .select_from(SavedAnalysis)
        .where(SavedAnalysis.workspace_id == workspace_id)
    )
    if count >= 100:
        raise HTTPException(
            409, "This workspace already has 100 analyses. Edit an existing analysis."
        )
    analysis = SavedAnalysis(
        workspace_id=workspace_id, title=body.title, query=body.query.model_dump(mode="json")
    )
    db.add(analysis)
    db.flush()
    row.analysis_id, row.accepted_hash = analysis.id, digest
    return analysis
