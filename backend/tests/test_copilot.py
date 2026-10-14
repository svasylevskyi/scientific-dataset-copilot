"""Real PostgreSQL admissions, cost settlement, isolation and confirmation boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_accounts import HEADERS, post, register
from test_copilot_provider import VALID
from test_plans import configure, plans, promote  # noqa: F401

from app.accounts.models import User
from app.analyses.models import AnalysisRun, SavedAnalysis
from app.copilot import provider, service
from app.copilot.config import CopilotConfig, config
from app.copilot.models import PlanningRequest
from app.copilot.schemas import Intent, PlanningInput
from app.db import engine
from app.main import app
from app.plans.models import UsageReservation, WorkspacePlan

pytestmark = pytest.mark.postgres


@pytest.fixture
def planner(plans, monkeypatch):  # noqa: F811
    client, sent = plans
    account = register(client, sent)
    monkeypatch.setenv("SDC_COPILOT_ENABLED", "true")
    monkeypatch.setenv("SDC_OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("SDC_COPILOT_DAILY_REQUESTS", "20")
    monkeypatch.setenv("SDC_COPILOT_DAILY_BUDGET_USD", "2.00")
    calls = []

    async def extract(body, key):
        # This independent connection would fail NOWAIT if auth/membership locks spanned I/O.
        with Session(engine()) as db, db.begin():
            db.scalar(
                select(User).where(User.id == UUID(account["id"])).with_for_update(nowait=True)
            )
            db.scalar(
                select(WorkspacePlan)
                .where(WorkspacePlan.workspace_id == UUID(account["workspace"]["id"]))
                .with_for_update(nowait=True)
            )
        calls.append(body)
        return provider.ProviderResult(
            Intent.model_validate(VALID), input_tokens=1000, cached_tokens=200, output_tokens=100
        )

    monkeypatch.setattr(provider, "extract", extract)
    return client, sent, account, calls


def ask(client, prompt="SST Madeira in 2023", key=None, parent=None):
    return post(
        client,
        "copilot/requests",
        {
            "request_key": str(key or uuid4()),
            "prompt": prompt,
            "parent_id": parent,
        },
    )


def test_plan_edit_accept_and_explicit_run_are_separate(planner):
    client, _, account, calls = planner
    key = uuid4()
    response = ask(client, key=key)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert (
        plan["status"] == "ready"
        and plan["proposal"]["analysis"]["query"]["region_id"] == "madeira"
    )
    assert ask(client, key=key).json() == plan
    assert len(calls) == 1
    assert ask(client, prompt="different request", key=key).status_code == 409
    assert client.get("/api/v1/analyses").json() == []
    assert client.get("/api/v1/account/usage").json()["reserved"] == 0
    edited = plan["proposal"]["analysis"] | {"title": "Reviewed Madeira"}
    edited["query"]["end"] = "2023-01-31"
    assert post(client, "copilot/preview", edited).status_code == 200
    saved = post(client, f"copilot/requests/{key}/accept", edited)
    assert saved.status_code == 200, saved.text
    assert post(client, f"copilot/requests/{key}/accept", edited).json()["id"] == saved.json()["id"]
    assert (
        post(client, f"copilot/requests/{key}/accept", edited | {"title": "Other"}).status_code
        == 409
    )
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(SavedAnalysis)) == 1
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == 0
        assert db.scalar(select(func.count()).select_from(UsageReservation)) == 0
        record = db.get(PlanningRequest, key)
        assert record.estimated_cost_usd == Decimal("0.001065")
    saved = saved.json()
    run = post(
        client,
        f"analyses/{saved['id']}/runs",
        {"run_key": str(uuid4()), "version": saved["version"]},
    )
    assert run.status_code == 202
    assert run.json()["query"] == edited["query"]
    assert client.get("/api/v1/account/usage").json()["reserved"] == 1
    assert client.get("/api/v1/admin/copilot/usage").status_code == 403
    promote(account)
    costs = client.get("/api/v1/admin/copilot/usage").json()
    assert costs["requests"] == 1 and Decimal(costs["estimated_cost_usd"]) > 0
    assert "transcript" not in costs


def test_clarification_context_turn_limit_and_unsupported_requests(planner, monkeypatch):
    client, _, _, calls = planner

    async def clarify(body, key):
        calls.append(body)
        return provider.ProviderResult(
            Intent.model_validate(VALID | {"start": None, "end": None, "clarification": "dates"}),
            input_tokens=100,
            cached_tokens=0,
            output_tokens=40,
        )

    monkeypatch.setattr(provider, "extract", clarify)
    first = ask(client, "Sea temperature near Madeira").json()
    assert first["status"] == "clarification" and first["proposal"] is None
    second = ask(client, "Recently", parent=first["id"]).json()
    third = ask(client, "In summer", parent=second["id"]).json()
    assert third["turn"] == 3
    assert calls[-1]["input"][0]["content"] == "Sea temperature near Madeira"
    assert len(calls[-1]["input"]) == 5
    assert ask(client, "More", parent=third["id"]).status_code == 409
    assert len(calls) == 3

    async def unsupported(*args):
        return provider.ProviderResult(Intent.model_validate(VALID | {"operation": "unsupported"}))

    monkeypatch.setattr(provider, "extract", unsupported)
    result = ask(client, "Rainfall in Spain").json()
    assert result["status"] == "unsupported" and result["proposal"] is None
    assert client.get("/api/v1/analyses").json() == []


def test_failures_keep_unknown_cost_reservation_without_consuming_analysis(planner, monkeypatch):
    client, _, _, _ = planner

    async def failed(*args):
        return provider.ProviderResult(error="unavailable")

    monkeypatch.setattr(provider, "extract", failed)
    key = uuid4()
    result = ask(client, key=key).json()
    assert result["status"] == "failed" and result["proposal"] is None
    with Session(engine()) as db:
        row = db.get(PlanningRequest, key)
        assert row.estimated_cost_usd is None and row.reserved_usd > 0
        assert service.costs(db, config()).budget_used_usd == row.reserved_usd
    assert client.get("/api/v1/account/usage").json()["reserved"] == 0
    assert client.get("/api/v1/copilot/status").json()["remaining"] == 19


def test_owner_isolation_csrf_and_disabled_manual_fallback(planner, monkeypatch):
    client, sent, owner_account, calls = planner
    result = ask(client).json()
    body = result["proposal"]["analysis"]
    with TestClient(app, headers=HEADERS) as other:
        account = register(other, sent, "other@example.com")
        promote(account)
        assert other.get(f"/api/v1/copilot/requests/{result['id']}").status_code == 404
        assert post(other, f"copilot/requests/{result['id']}/accept", body).status_code == 404
        assert ask(other, parent=result["id"]).status_code == 404
    assert (
        client.post(
            "/api/v1/copilot/requests",
            json={"request_key": str(uuid4()), "prompt": "SST"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    with TestClient(app, headers=HEADERS) as anonymous:
        assert anonymous.get("/api/v1/copilot/status").status_code == 401
        assert ask(anonymous).status_code == 401
    with Session(engine()) as db, db.begin():
        db.get(WorkspacePlan, UUID(owner_account["workspace"]["id"])).status = "suspended"
    assert ask(client).status_code == 403
    assert post(client, f"copilot/requests/{result['id']}/accept", body).status_code == 403
    with Session(engine()) as db, db.begin():
        db.get(WorkspacePlan, UUID(owner_account["workspace"]["id"])).status = "active"
    monkeypatch.setenv("SDC_COPILOT_ENABLED", "false")
    assert client.get("/api/v1/copilot/status").json()["enabled"] is False
    assert ask(client).status_code == 503
    assert post(client, "analyses", body).status_code == 201
    assert len(calls) == 1
    assert (
        client.get(f"/api/v1/copilot/requests/{result['id']}").headers["cache-control"]
        == "no-store"
    )


def test_daily_limit_and_invalid_proposals(planner, monkeypatch):
    client, _, _, calls = planner
    monkeypatch.setenv("SDC_COPILOT_DAILY_REQUESTS", "1")
    result = ask(client).json()
    assert ask(client).status_code == 429 and len(calls) == 1
    draft = result["proposal"]["analysis"]
    for query in [
        draft["query"] | {"end": "2099-01-01"},
        draft["query"] | {"start": "1970-01-01"},
        draft["query"] | {"region_id": "other"},
    ]:
        assert post(client, "copilot/preview", draft | {"query": query}).status_code == 422
        assert (
            post(
                client, f"copilot/requests/{result['id']}/accept", draft | {"query": query}
            ).status_code
            == 422
        )
    configure(max_date_range_days=30)
    assert post(client, "copilot/preview", draft).status_code == 422
    configure(max_date_range_days=3663, monthly_analyses=0)
    assert post(client, "copilot/preview", draft).json()["can_run"] is False
    assert post(client, f"copilot/requests/{result['id']}/accept", draft).status_code == 200


def test_global_budget_is_atomic_across_workspaces(planner):
    client, sent, account, _ = planner
    workspaces = [UUID(account["workspace"]["id"])]
    for n in range(3):
        with TestClient(app, headers=HEADERS) as other:
            workspaces.append(
                UUID(register(other, sent, f"budget{n}@example.com")["workspace"]["id"])
            )
    with Session(engine()) as db:
        today = service.clock(db).date()
    required = provider.reservation(
        provider.payload([{"role": "user", "content": "SST Madeira in 2023"}], today)
    )
    cfg = CopilotConfig(True, "test-only", daily_budget_usd=required)

    def admit(ws):
        try:
            with Session(engine()) as db, db.begin():
                service.admit(
                    db, ws, PlanningInput(request_key=uuid4(), prompt="SST Madeira in 2023"), cfg
                )
                return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(admit, workspaces)) == 1
    with Session(engine()) as db:
        assert service.costs(db, cfg).budget_used_usd == required


def test_duplicate_and_pending_requests_cannot_dispatch_twice_and_orphans_stay_charged(planner):
    _, _, account, _ = planner
    ws = UUID(account["workspace"]["id"])
    body = PlanningInput(request_key=uuid4(), prompt="SST Madeira in 2023")

    def admit(_):
        with Session(engine()) as db, db.begin():
            return service.admit(db, ws, body, config())[1] is not None

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(admit, range(4))) == 1
    with Session(engine()) as db, db.begin():
        with pytest.raises(HTTPException) as error:
            service.admit(db, ws, PlanningInput(request_key=uuid4(), prompt="Other SST"), config())
        assert error.value.status_code == 409
    with Session(engine()) as db, db.begin():
        db.get(PlanningRequest, body.request_key).created_at -= timedelta(seconds=121)
    with Session(engine()) as db, db.begin():
        row, outbound = service.admit(db, ws, body, config())
        assert row.status == "failed" and outbound is None
        assert row.estimated_cost_usd is None
        assert service.costs(db, config()).budget_used_usd > 0
    with Session(engine()) as db, db.begin():
        service.finish(
            db,
            body.request_key,
            provider.ProviderResult(
                Intent.model_validate(VALID),
                input_tokens=1000,
                cached_tokens=200,
                output_tokens=100,
            ),
        )
        row = db.get(PlanningRequest, body.request_key)
        assert row.status == "failed" and row.proposal is None
        assert row.estimated_cost_usd == Decimal("0.001065")


def test_application_validation_rejects_unrunnable_intents(planner):
    _, _, account, _ = planner
    ws = UUID(account["workspace"]["id"])
    for change in (
        {"start": "2024-01-01", "end": "2023-01-01"},
        {"end": "2099-01-01"},
        {"start": None},
        {"region_id": None},
        {"operation": "unclear"},
    ):
        with Session(engine()) as db, db.begin():
            state, _, proposal = service.interpret(db, ws, Intent.model_validate(VALID | change))
            assert state == "clarification" and proposal is None
