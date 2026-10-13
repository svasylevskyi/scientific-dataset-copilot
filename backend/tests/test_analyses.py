"""Durability, fencing, transaction and owner isolation tests against PostgreSQL."""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_accounts import HEADERS, post, register
from test_plans import configure, plans, promote  # noqa: F401

from app.analyses import service, storage, worker
from app.analyses.models import AnalysisRun, RunArtifact, RunEvent, SavedAnalysis
from app.db import engine
from app.main import app
from app.plans.models import UsageEvent, UsageReservation

pytestmark = pytest.mark.postgres
QUERY = {"region_id": "canaries", "start": "2020-01-01", "end": "2020-01-31"}


@pytest.fixture
def workspace(plans, tmp_path, monkeypatch):  # noqa: F811
    client, sent = plans
    account = register(client, sent)
    monkeypatch.setenv("SDC_ARTIFACT_DIR", str(tmp_path / "runs"))
    worker.STOP.clear()
    yield client, sent, account
    worker.STOP.clear()


def create(client, query=None):
    response = post(client, "analyses", {"title": "Canaries January", "query": query or QUERY})
    assert response.status_code == 201, response.text
    return response.json()


def start(client, analysis, key=None):
    response = post(
        client,
        f"analyses/{analysis['id']}/runs",
        {
            "run_key": str(key or uuid4()),
            "version": analysis["version"],
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def claim():
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        return service.claim(db)


def finish(job, **kwargs):
    with Session(engine()) as db, db.begin():
        return service.finish(
            db,
            job.id,
            job.workspace_id,
            job.lease_token,
            outcome=kwargs.pop("outcome", "failed"),
            message="Test outcome",
            **kwargs,
        )


def usage(client):
    return client.get("/api/v1/account/usage").json()


def test_atomic_submission_idempotency_and_immutable_edits(workspace):
    client, _, account = workspace
    analysis = create(client)
    key = uuid4()
    ws = UUID(account["workspace"]["id"])

    def submit(_):
        with Session(engine()) as db, db.begin():
            return service.submit(db, ws, UUID(analysis["id"]), key, 1).id

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(submit, range(4))) == {key}
    assert usage(client)["reserved"] == 1
    update = {"title": "Updated query", "query": QUERY | {"end": "2020-02-29"}, "version": 1}
    assert client.patch(f"/api/v1/analyses/{analysis['id']}", json=update).status_code == 200
    assert client.patch(f"/api/v1/analyses/{analysis['id']}", json=update).status_code == 409
    # An uncertain HTTP response can be retried after the saved query was edited.
    run = start(client, analysis, key)
    assert run["query"] == QUERY and run["title"] == "Canaries January"
    assert (
        post(
            client, f"analyses/{analysis['id']}/runs", {"run_key": str(uuid4()), "version": 1}
        ).status_code
        == 409
    )
    assert (
        post(
            client, f"analyses/{analysis['id']}/runs", {"run_key": str(key), "version": 2}
        ).status_code
        == 409
    )
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == 1
        assert db.scalar(select(func.count()).select_from(UsageReservation)) == 1
        assert db.scalar(select(func.count()).select_from(UsageEvent)) == 1


def test_job_persistence_rollback_restores_quota(workspace):
    client, _, account = workspace
    analysis = create(client)
    with Session(engine()) as db:
        service.submit(db, UUID(account["workspace"]["id"]), UUID(analysis["id"]), uuid4(), 1)
        db.rollback()
    assert usage(client)["reserved"] == 0
    assert client.get(f"/api/v1/analyses/{analysis['id']}/runs").json() == []


def test_access_validation_and_owner_isolation_even_for_admin(workspace):
    client, sent, _ = workspace
    analysis = create(client)
    run = start(client, analysis)
    with TestClient(app, headers=HEADERS) as second:
        admin = register(second, sent, "other@example.com")
        promote(admin)
        assert second.get("/api/v1/analyses").json() == []
        for path in [
            f"runs/{run['id']}",
            f"runs/{run['id']}/result",
            f"runs/{run['id']}/artifacts/{uuid4()}",
            f"analyses/{analysis['id']}/runs",
        ]:
            assert second.get(f"/api/v1/{path}").status_code == 404
        assert post(second, f"runs/{run['id']}/cancel").status_code == 404
        assert (
            post(
                second, f"analyses/{analysis['id']}/runs", {"run_key": str(uuid4()), "version": 1}
            ).status_code
            == 404
        )
    assert (
        client.post(
            "/api/v1/analyses",
            json={"title": "Bad", "query": QUERY},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        post(
            client, "analyses", {"title": "Bad", "query": QUERY | {"url": "http://localhost"}}
        ).status_code
        == 422
    )
    assert (
        post(
            client,
            "analyses",
            {"title": "Bad", "query": QUERY | {"start": "2099-01-01", "end": "2099-02-01"}},
        ).status_code
        == 422
    )
    assert client.get(f"/api/v1/runs/{run['id']}").headers["cache-control"] == "no-store"


def test_queued_and_running_cancellation_settle_once(workspace):
    client, _, _ = workspace
    analysis = create(client)
    queued = start(client, analysis)
    assert post(client, f"runs/{queued['id']}/cancel").json()["status"] == "cancelled"
    assert post(client, f"runs/{queued['id']}/cancel").json()["status"] == "cancelled"
    assert claim() is None
    running = start(client, analysis)
    job = claim()
    assert post(client, f"runs/{running['id']}/cancel").json()["status"] == "running"
    assert usage(client)["reserved"] == 1
    with Session(engine()) as db, db.begin():
        assert service.heartbeat(db, job.id, job.workspace_id, job.lease_token) == "cancel"
    assert finish(job, outcome="succeeded")  # Cancellation wins before publication.
    assert not finish(job)
    assert usage(client)["reserved"] == 0 and usage(client)["consumed"] == 0
    with Session(engine()) as db:
        assert db.get(AnalysisRun, job.id).status == "cancelled"
        assert db.scalar(select(func.count()).select_from(UsageEvent)) == 4


def test_worker_claim_concurrency_and_recovery_fences_stale_attempt(workspace):
    client, _, _ = workspace
    analysis = create(client)
    run = start(client, analysis)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: claim(), range(4)))
    first = next(job for job in jobs if job)
    assert sum(job is not None for job in jobs) == 1
    with Session(engine()) as db, db.begin():
        row = db.get(AnalysisRun, first.id)
        row.lease_until = service.clock(db) - timedelta(seconds=1)
    assert claim() is None  # A lost heartbeat alone cannot release/restart active work.
    with Session(engine()) as db, db.begin():
        db.get(AnalysisRun, first.id).attempt_deadline = service.clock(db) - timedelta(seconds=1)
    second = claim()
    assert second.id == UUID(run["id"]) and second.attempt == 2
    assert second.lease_token != first.lease_token
    assert not finish(first)
    assert usage(client)["reserved"] == 1
    assert finish(second)
    assert usage(client)["remaining"] == 20


def test_retries_are_bounded_and_do_not_reserve_again(workspace):
    client, _, _ = workspace
    start(client, create(client))
    for attempt in range(1, 4):
        job = claim()
        assert job.attempt == attempt
        assert finish(job, retry=True)
        with Session(engine()) as db, db.begin():
            row = db.get(AnalysisRun, job.id)
            if attempt < 3:
                assert row.status == "queued" and usage(client)["reserved"] == 1
                row.available_at = service.clock(db) - timedelta(seconds=1)
            else:
                assert row.status == "failed"
    assert claim() is None
    assert usage(client)["reserved"] == 0
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(UsageReservation)) == 1


def test_real_child_pipeline_publication_exports_and_retention(workspace):
    client, _, _ = workspace
    analysis = create(client)
    submitted = start(client, analysis)
    job = claim()
    worker.execute(
        job,
        pipeline_command=[
            sys.executable,
            str(Path(__file__).with_name("analysis_fixture_worker.py")),
        ],
    )
    result = client.get(f"/api/v1/runs/{job.id}").json()
    assert result["status"] == "succeeded", result
    assert len(result["artifacts"]) == 6
    data = client.get(f"/api/v1/runs/{job.id}/result").json()
    assert data["received_days"] == 31 and len(data["months"]) == 1
    assert 15 < data["months"][0]["mean_celsius"] < 30
    csv = next(item for item in result["artifacts"] if item["name"] == "monthly.csv")
    download = client.get(f"/api/v1/runs/{job.id}/artifacts/{csv['id']}")
    assert download.status_code == 200 and "mean_sst_celsius" in download.text
    assert "attachment" in download.headers["content-disposition"]
    assert usage(client)["consumed"] == 1 and usage(client)["reserved"] == 0
    assert not finish(job)
    assert start(client, analysis, UUID(submitted["id"]))["status"] == "succeeded"
    with Session(engine()) as db, db.begin():
        db.get(AnalysisRun, job.id).expires_at = service.clock(db) - timedelta(seconds=1)
    assert client.get(f"/api/v1/runs/{job.id}/result").status_code == 410
    assert client.get(f"/api/v1/runs/{job.id}/artifacts/{csv['id']}").status_code == 410
    with Session(engine()) as db, db.begin():
        assert storage.cleanup(db) == 1
    with Session(engine()) as db, db.begin():
        assert storage.cleanup(db) == 0
        assert db.get(SavedAnalysis, UUID(analysis["id"]))
        assert db.scalar(select(func.count()).select_from(RunArtifact)) == 6
        assert db.scalar(select(func.count()).select_from(RunEvent)) >= 3
    assert not storage.safe_path(str(job.id)).exists()
    assert usage(client)["consumed"] == 1


def test_date_limit_and_monthly_limit_enforced_on_real_jobs(workspace):
    client, _, _ = workspace
    analysis = create(client)
    configure(max_date_range_days=30)
    body = {"run_key": str(uuid4()), "version": 1}
    assert post(client, f"analyses/{analysis['id']}/runs", body).status_code == 403
    assert usage(client)["reserved"] == 0
    configure(max_date_range_days=3663, monthly_analyses=0)
    assert post(client, f"analyses/{analysis['id']}/runs", body).status_code == 403


def test_parent_stops_child_before_cancellation_settlement(workspace, monkeypatch):
    client, _, _ = workspace
    run = start(client, create(client))
    job = claim()
    post(client, f"runs/{run['id']}/cancel")
    stopped = []

    class Child:
        def poll(self):
            return None

        def terminate(self):
            stopped.append(True)

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: Child())
    worker.execute(job)
    assert stopped and usage(client)["reserved"] == 0
