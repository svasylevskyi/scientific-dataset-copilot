"""Entitlement checks use real PostgreSQL locks and independent transactions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from test_accounts import HEADERS, post, register

from app.accounts.models import User
from app.db import engine
from app.main import app
from app.plans.models import (
    Plan,
    PlanSettings,
    ProcessingCost,
    UsageEvent,
    UsageReservation,
)
from app.plans.service import month_bounds, record_cost, reserve, settle, usage_view

pytestmark = pytest.mark.postgres
DEFAULT_ID = UUID("e9b70a10-7b56-4f3e-8af7-a5d6f693b111")
FINGERPRINT = "a" * 64


@pytest.fixture
def plans(accounts):
    reset_plans()
    yield accounts
    with engine().begin() as connection:
        connection.execute(text("TRUNCATE users, auth_rate_buckets CASCADE"))
    reset_plans()


def reset_plans():
    with Session(engine()) as db, db.begin():
        db.get(PlanSettings, 1).default_plan_id = DEFAULT_ID
        db.flush()
        db.execute(delete(Plan).where(Plan.id != DEFAULT_ID))
        plan = db.get(Plan, DEFAULT_ID)
        plan.name = "Development"
        plan.active = True
        plan.monthly_analyses = 20
        plan.concurrent_analyses = 1
        plan.max_date_range_days = 3663
        plan.retention_days = 30
        plan.version = 1


def promote(account):
    with Session(engine()) as db, db.begin():
        db.get(User, UUID(account["id"])).role = "admin"


def plan_body(**overrides):
    return dict(
        name="Research",
        description="A second free plan",
        active=True,
        monthly_analyses=5,
        concurrent_analyses=2,
        max_date_range_days=365,
        retention_days=60,
        **overrides,
    )


def configure(**values):
    with Session(engine()) as db, db.begin():
        plan = db.get(Plan, DEFAULT_ID)
        for key, value in values.items():
            setattr(plan, key, value)


def workspace(account):
    return UUID(account["workspace"]["id"])


def admit(workspace_id, key=None, **values):
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        return reserve(
            db,
            workspace_id,
            key or uuid4(),
            requested_days=values.get("days", 31),
            request_hash=values.get("request_hash", FINGERPRINT),
        )


def finish(workspace_id, key, outcome="succeeded"):
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        return settle(db, workspace_id, key, outcome)


def test_existing_workspaces_are_backfilled_without_resetting_accounts(postgres, plans):
    client, sent = plans
    account = register(client, sent)
    command.downgrade(postgres, "0001_accounts")
    command.upgrade(postgres, "head")
    result = client.get("/api/v1/account/usage")
    assert result.status_code == 200, result.text
    assert result.json()["plan"]["name"] == "Development"
    assert result.json()["remaining"] == 20
    assert client.get("/api/v1/auth/me").json()["id"] == account["id"]
    configure(monthly_analyses=7)
    command.upgrade(postgres, "head")
    assert client.get("/api/v1/account/usage").json()["remaining"] == 7
    command.check(postgres)


def test_default_selection_new_signup_and_existing_assignment(plans):
    client, sent = plans
    first = register(client, sent)
    promote(first)
    created = post(client, "admin/plans", plan_body())
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["billing"] == "free"
    assert (
        post(client, f"admin/plans/{plan['id']}/default", {"version": plan["version"]}).status_code
        == 200
    )
    assert client.get("/api/v1/account/usage").json()["plan"]["id"] == str(DEFAULT_ID)
    with TestClient(app, headers=HEADERS) as second:
        register(second, sent, "second@example.com")
        usage = second.get("/api/v1/account/usage").json()
        assert usage["plan"]["id"] == plan["id"] and usage["remaining"] == 5
    listed = client.get("/api/v1/admin/plans").json()
    assert sum(p["is_default"] for p in listed) == 1
    assert sum(p["workspace_count"] for p in listed) == 2


def test_permissions_csrf_input_validation_and_owner_isolation(plans):
    client, sent = plans
    assert client.get("/api/v1/account/usage").status_code == 401
    account = register(client, sent)
    assert client.get("/api/v1/admin/plans").status_code == 403
    assert post(client, "admin/plans", plan_body()).status_code == 403
    admit(workspace(account))
    with TestClient(app, headers=HEADERS) as second:
        register(second, sent, "second@example.com")
        data = second.get("/api/v1/account/usage").json()
        assert data["recent"] == [] and data["remaining"] == 20
        assert second.get(f"/api/v1/workspaces/{workspace(account)}").status_code == 404
        assert post(second, "account/usage", {"remaining": 999}).status_code == 405
        assert (
            post(
                second,
                "admin/plan-assignments",
                {
                    "email": "first@example.com",
                    "plan_id": str(DEFAULT_ID),
                    "status": "active",
                },
            ).status_code
            == 403
        )
    promote(account)
    assert (
        client.post(
            "/api/v1/admin/plans", json=plan_body(), headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    for override in [
        {"monthly_analyses": -1},
        {"concurrent_analyses": 0},
        {"monthly_analyses": 1.5},
        {"monthly_analyses": True},
        {"retention_days": 0},
        {"max_date_range_days": 3664},
        {"billing": "paid"},
    ]:
        assert post(client, "admin/plans", plan_body() | override).status_code == 422
    assert post(client, "admin/plans", plan_body() | {"name": "development"}).status_code == 409
    assert client.get("/api/v1/account/usage").headers["Cache-Control"] == "no-store"


def test_plan_edits_archiving_and_assignments_keep_usage(plans):
    client, sent = plans
    account = register(client, sent)
    promote(account)
    ws = workspace(account)
    run = admit(ws)
    finish(ws, run.run_key)
    second = post(client, "admin/plans", plan_body()).json()
    initial = client.get("/api/v1/admin/plans").json()[0]
    fields = {k: initial[k] for k in plan_body()}
    response = client.patch(
        f"/api/v1/admin/plans/{DEFAULT_ID}",
        json=fields
        | {
            "monthly_analyses": 0,
            "retention_days": 10,
            "version": initial["version"],
        },
    )
    assert response.status_code == 200, response.text
    assert (
        client.patch(f"/api/v1/admin/plans/{DEFAULT_ID}", json=fields | {"version": 1}).status_code
        == 409
    )
    assert client.get("/api/v1/account/usage").json()["remaining"] == 0
    with pytest.raises(HTTPException) as error:
        admit(ws)
    assert error.value.status_code == 403
    with Session(engine()) as db:
        assert db.get(UsageReservation, run.id).retention_days == 30
    # The current default cannot be archived, even if the UI is bypassed.
    fields.update(active=False)
    assert (
        client.patch(f"/api/v1/admin/plans/{DEFAULT_ID}", json=fields | {"version": 2}).status_code
        == 409
    )
    assert post(client, f"admin/plans/{second['id']}/default", {"version": 1}).status_code == 200
    assert (
        client.patch(f"/api/v1/admin/plans/{DEFAULT_ID}", json=fields | {"version": 2}).status_code
        == 200
    )
    # Archiving doesn't revoke existing access or reset consumption.
    assert client.get("/api/v1/account/usage").json()["consumed"] == 1
    run2 = admit(ws)
    finish(ws, run2.run_key, "cancelled")
    assert post(client, f"admin/plans/{DEFAULT_ID}/default", {"version": 3}).status_code == 409
    assert (
        post(
            client,
            "admin/plan-assignments",
            {
                "email": "first@example.com",
                "plan_id": str(DEFAULT_ID),
                "status": "active",
            },
        ).status_code
        == 409
    )
    assert (
        post(
            client,
            "admin/plan-assignments",
            {
                "email": "first@example.com",
                "plan_id": second["id"],
                "status": "active",
            },
        ).status_code
        == 200
    )
    data = client.get("/api/v1/account/usage").json()
    assert data["consumed"] == 1 and data["remaining"] == 4
    # Suspension blocks admission but still lets an accepted run settle.
    run3 = admit(ws)
    assert (
        post(
            client,
            "admin/plan-assignments",
            {
                "email": "first@example.com",
                "plan_id": second["id"],
                "status": "suspended",
            },
        ).status_code
        == 200
    )
    with pytest.raises(HTTPException, match="suspended"):
        admit(ws)
    finish(ws, run3.run_key)
    assert client.get("/api/v1/account/usage").json()["consumed"] == 2


@pytest.mark.parametrize("limit,concurrent,expected", [(2, 10, 2), (20, 1, 1)])
def test_concurrent_reservations_cannot_overspend(plans, limit, concurrent, expected):
    client, sent = plans
    ws = workspace(register(client, sent))
    configure(monthly_analyses=limit, concurrent_analyses=concurrent)
    barrier = Barrier(6)

    def submit(_):
        barrier.wait(timeout=10)
        try:
            admit(ws)
            return "accepted"
        except HTTPException as error:
            assert error.status_code == 403
            return "blocked"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(submit, range(6)))
    assert results.count("accepted") == expected
    data = client.get("/api/v1/account/usage").json()
    assert data["reserved"] == expected and data["concurrent_reserved"] == expected


def test_concurrent_retry_and_terminal_events_are_idempotent(plans):
    client, sent = plans
    ws = workspace(register(client, sent))
    key = uuid4()
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda _: admit(ws, key), range(4)))
    assert len({r.id for r in runs}) == 1
    with pytest.raises(HTTPException) as conflict:
        admit(ws, key, request_hash="b" * 64)
    assert conflict.value.status_code == 409
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: finish(ws, key), range(4)))
    # A late retry doesn't consume a second unit or re-open a completed run.
    assert admit(ws, key).status == "consumed"
    with pytest.raises(HTTPException) as conflict:
        finish(ws, key, "failed")
    assert conflict.value.status_code == 409
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(UsageReservation)) == 1
        assert db.scalar(select(func.count()).select_from(UsageEvent)) == 2
    data = client.get("/api/v1/account/usage").json()
    assert data["consumed"] == 1 and data["reserved"] == 0


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_failure_and_cancellation_release_quota_but_keep_costs(plans, outcome):
    client, sent = plans
    ws = workspace(register(client, sent))
    configure(monthly_analyses=1)
    run = admit(ws)
    cost_key = uuid4()

    def expense(_):
        with Session(engine(), expire_on_commit=False) as db, db.begin():
            return record_cost(
                db, run.id, cost_key, category="compute", amount_usd=Decimal("0.0025")
            ).id

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert len(set(pool.map(expense, range(3)))) == 1
    finish(ws, run.run_key, outcome)
    finish(ws, run.run_key, outcome)
    assert admit(ws, run.run_key).status == "released"
    data = client.get("/api/v1/account/usage").json()
    assert data["remaining"] == 1 and data["reserved"] == 0
    assert data["recent"][0]["release_reason"] == outcome
    with Session(engine()) as db:
        assert db.scalar(select(ProcessingCost.amount_usd)) == Decimal("0.0025")
        assert db.scalar(select(func.count()).select_from(UsageEvent)) == 2
    admit(ws)  # A deliberate new run can use the released unit.


def test_rollbacks_and_validation_leave_no_reservation(plans):
    client, sent = plans
    ws = workspace(register(client, sent))
    configure(max_date_range_days=30)
    with pytest.raises(HTTPException):
        admit(ws, days=31)
    key = uuid4()
    with Session(engine()) as db:
        reserve(db, ws, key, requested_days=30, request_hash=FINGERPRINT)
        db.rollback()  # Simulates failure to persist a future job/outbox.
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(UsageReservation)) == 0
        assert db.scalar(select(func.count()).select_from(UsageEvent)) == 0
    assert admit(ws, key, days=30).status == "reserved"


def test_utc_month_boundary_and_pending_previous_month(plans, monkeypatch):
    client, sent = plans
    ws = workspace(register(client, sent))
    moment = datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
    monkeypatch.setattr("app.plans.service.now", lambda: moment)
    run = admit(ws)
    moment += timedelta(minutes=2)
    with Session(engine()) as db, db.begin():
        current = usage_view(db, ws)
        assert current.period_start == date(2027, 1, 1)
        assert current.remaining == 20 and current.reserved == 0
        assert current.concurrent_reserved == 1 and not current.can_reserve
    with pytest.raises(HTTPException):
        admit(ws)
    finish(ws, run.run_key)
    assert client.get("/api/v1/account/usage").json()["consumed"] == 0
    next_run = admit(ws)
    with Session(engine()) as db:
        assert db.get(UsageReservation, run.id).period_start == date(2026, 12, 1)
        assert db.get(UsageReservation, next_run.id).period_start == date(2027, 1, 1)
    assert month_bounds(datetime(2027, 1, 1, 1, tzinfo=timezone(timedelta(hours=2)))) == (
        date(2026, 12, 1),
        date(2027, 1, 1),
    )


def test_concurrent_admin_edits_detect_stale_versions(plans):
    client, sent = plans
    account = register(client, sent)
    promote(account)
    cookie = client.cookies.get("sdc_session")
    body = plan_body() | {"name": "Development", "version": 1}
    barrier = Barrier(2)

    def change(limit):
        with TestClient(app, headers=HEADERS) as tab:
            tab.cookies.set("sdc_session", cookie)
            barrier.wait(timeout=10)
            return tab.patch(
                f"/api/v1/admin/plans/{DEFAULT_ID}", json=body | {"monthly_analyses": limit}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, [4, 8])) == [200, 409]
