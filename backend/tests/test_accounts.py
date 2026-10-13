"""Real PostgreSQL integration tests. Never point SDC_TEST_DATABASE_URL at user data."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.accounts.models import AuthSession, EmailToken, RateBucket, User, Workspace
from app.accounts.security import digest, now
from app.config import settings
from app.db import engine
from app.main import app

pytestmark = pytest.mark.postgres
PASSWORD = "A private test passphrase 123!"
HEADERS = {"Origin": "http://127.0.0.1:5173", "X-SDC-Request": "1"}


@pytest.fixture(scope="module")
def postgres():
    url = os.getenv("SDC_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set SDC_TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test")
    assert make_url(url).database.endswith("_test"), "Integration database must end in _test"
    previous = os.environ.get("SDC_DATABASE_URL")
    os.environ["SDC_DATABASE_URL"] = url
    settings.cache_clear()
    engine.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    yield config
    engine().dispose()
    engine.cache_clear()
    if previous is None:
        os.environ.pop("SDC_DATABASE_URL", None)
    else:
        os.environ["SDC_DATABASE_URL"] = previous
    settings.cache_clear()


@pytest.fixture
def accounts(postgres, monkeypatch):
    with engine().begin() as connection:
        connection.execute(
            text(
                "TRUNCATE users, workspaces, auth_sessions, email_tokens, auth_rate_buckets CASCADE"
            )
        )
    sent = []
    monkeypatch.setattr(
        "app.accounts.mail.send_link",
        lambda email, purpose, token: sent.append(
            {
                "email": email,
                "purpose": purpose,
                "token": token,
            }
        ),
    )
    with TestClient(app, headers=HEADERS) as client:
        yield client, sent


def clear_limits():
    with engine().begin() as connection:
        connection.execute(delete(RateBucket))


def post(client, path, body=None):
    return client.post(f"/api/v1/{path}", json=body or {})


def register(client, sent, email="first@example.com"):
    response = post(
        client, "auth/register", {"name": "First User", "email": email, "password": PASSWORD}
    )
    assert response.status_code == 202, response.text
    token = next(item["token"] for item in reversed(sent) if item["email"] == email)
    assert post(client, "auth/verify", {"token": token}).status_code == 200
    response = post(client, "auth/login", {"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def test_migration_round_trip_and_schema_match(postgres, accounts):
    command.check(postgres)
    command.downgrade(postgres, "base")
    command.upgrade(postgres, "head")
    command.check(postgres)


def test_account_journey_persistence_and_logout(accounts):
    client, sent = accounts
    account = register(client, sent)
    assert account["verified"] and account["role"] == "user"
    assert client.get(f"/api/v1/workspaces/{account['workspace']['id']}").status_code == 200
    response = client.patch("/api/v1/account", json={"name": "Updated Name"})
    assert response.json()["name"] == "Updated Name"
    cookie = client.cookies.get("sdc_session")
    assert cookie
    # A new engine and HTTP client simulate returning after application restart.
    engine().dispose()
    with TestClient(app, headers=HEADERS) as returning:
        returning.cookies.set("sdc_session", cookie)
        assert returning.get("/api/v1/auth/me").json()["name"] == "Updated Name"
        assert post(returning, "auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    with Session(engine()) as db:
        user = db.get(User, UUID(account["id"]))
        assert user.password_hash != PASSWORD
        assert db.scalar(select(EmailToken)).token_hash == digest(sent[0]["token"])
        assert db.scalar(select(AuthSession)).token_hash != cookie


def test_unverified_duplicate_registration_and_normalized_email(accounts):
    client, sent = accounts
    body = {"name": "Original", "email": "Mixed@EXAMPLE.com", "password": PASSWORD}
    assert post(client, "auth/register", body).status_code == 202
    first = sent[-1]["token"]
    assert (
        post(client, "auth/login", {"email": "mixed@example.com", "password": PASSWORD}).status_code
        == 403
    )
    clear_limits()
    body.update(name="Replacement", password="different long password")
    assert post(client, "auth/register", body).status_code == 202
    assert post(client, "auth/verify", {"token": first}).status_code == 400
    assert post(client, "auth/verify", {"token": sent[-1]["token"]}).status_code == 200
    response = post(client, "auth/login", {"email": "mixed@example.com", "password": PASSWORD})
    assert response.status_code == 200 and response.json()["name"] == "Original"
    assert post(client, "auth/verify", {"token": sent[-1]["token"]}).status_code == 400


def test_expired_and_wrong_purpose_links_and_resend(accounts):
    client, sent = accounts
    post(client, "auth/register", {"name": "A", "email": "a@example.com", "password": PASSWORD})
    token = sent[-1]["token"]
    assert (
        post(client, "auth/reset-password", {"token": token, "password": PASSWORD}).status_code
        == 400
    )
    with Session(engine()) as db, db.begin():
        db.scalar(select(EmailToken)).expires_at = now() - timedelta(seconds=1)
    assert post(client, "auth/verify", {"token": token}).status_code == 400
    clear_limits()
    assert post(client, "auth/resend-verification", {"email": "a@example.com"}).status_code == 202
    assert post(client, "auth/verify", {"token": sent[-1]["token"]}).status_code == 200


def test_workspace_session_and_admin_isolation(accounts):
    first, sent = accounts
    a = register(first, sent)
    a_session = first.get("/api/v1/account/sessions").json()[0]["id"]
    with TestClient(app, headers=HEADERS) as second:
        b = register(second, sent, "second@example.com")
        assert a["workspace"]["id"] != b["workspace"]["id"]
        assert second.get(f"/api/v1/workspaces/{a['workspace']['id']}").status_code == 404
        assert (
            second.delete(
                f"/api/v1/account/sessions/{a_session}",
                headers={"Content-Type": "application/json"},
            ).status_code
            == 404
        )
        assert second.get("/api/v1/admin/summary").status_code == 403
        with Session(engine()) as db, db.begin():
            db.get(User, UUID(b["id"])).role = "admin"
        assert second.get("/api/v1/admin/summary").json()["users"] == 2
        assert second.get(f"/api/v1/workspaces/{a['workspace']['id']}").status_code == 404
        assert (
            second.patch("/api/v1/account", json={"name": "B", "role": "admin"}).status_code == 422
        )
    assert first.get("/api/v1/auth/me").status_code == 200


def test_cookie_rotation_replay_and_expiration(accounts):
    client, sent = accounts
    register(client, sent)
    old = client.cookies.get("sdc_session")
    response = post(client, "auth/refresh")
    assert response.status_code == 200
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header and "SameSite=lax" in cookie_header
    assert "Path=/api/v1" in cookie_header
    current = client.cookies.get("sdc_session")
    assert old != current
    with TestClient(app, headers=HEADERS) as stale:
        stale.cookies.set("sdc_session", old)
        response = post(stale, "auth/refresh")
        assert response.status_code == 409 and "set-cookie" not in response.headers
        assert client.get("/api/v1/auth/me").status_code == 200
        with Session(engine()) as db, db.begin():
            db.scalar(select(AuthSession)).rotated_at = now() - timedelta(seconds=31)
        assert post(stale, "auth/refresh").status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 401
    post(client, "auth/login", {"email": "first@example.com", "password": PASSWORD})
    with Session(engine()) as db, db.begin():
        active = db.scalar(select(AuthSession).where(AuthSession.revoked_at.is_(None)))
        active.absolute_expires_at = now() - timedelta(seconds=1)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_concurrent_refresh_has_one_winner(accounts):
    client, sent = accounts
    register(client, sent)
    cookie = client.cookies.get("sdc_session")

    def renew(_):
        with TestClient(app, headers=HEADERS) as tab:
            tab.cookies.set("sdc_session", cookie)
            return post(tab, "auth/refresh")

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(renew, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    loser = next(r for r in responses if r.status_code == 409)
    assert "set-cookie" not in loser.headers
    winner = next(r for r in responses if r.status_code == 200)
    with TestClient(app) as tab:
        tab.cookies.set("sdc_session", winner.cookies.get("sdc_session"))
        assert tab.get("/api/v1/auth/me").status_code == 200


def test_password_reset_is_single_use_and_revokes_every_session(accounts):
    client, sent = accounts
    register(client, sent)
    with TestClient(app, headers=HEADERS) as second:
        post(second, "auth/login", {"email": "first@example.com", "password": PASSWORD})
        clear_limits()
        known = post(client, "auth/forgot-password", {"email": "first@example.com"})
        unknown = post(client, "auth/forgot-password", {"email": "unknown@example.com"})
        assert known.json() == unknown.json()
        token = sent[-1]["token"]
        body = {"token": token, "password": "The replacement passphrase!"}
        assert post(client, "auth/reset-password", body).status_code == 200
        assert post(client, "auth/reset-password", body).status_code == 400
        assert second.get("/api/v1/auth/me").status_code == 401
        assert (
            post(
                client, "auth/login", {"email": "first@example.com", "password": PASSWORD}
            ).status_code
            == 401
        )
        assert (
            post(
                client, "auth/login", {"email": "first@example.com", "password": body["password"]}
            ).status_code
            == 200
        )


def test_concurrent_reset_cannot_reuse_token(accounts):
    client, sent = accounts
    register(client, sent)
    clear_limits()
    post(client, "auth/forgot-password", {"email": "first@example.com"})
    token = sent[-1]["token"]

    def reset(_):
        with TestClient(app, headers=HEADERS) as tab:
            return post(
                tab,
                "auth/reset-password",
                {"token": token, "password": "Concurrent new passphrase!"},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(reset, range(2)))
    assert sorted(statuses) == [200, 400]


def test_email_change_stays_pending_then_revokes_sessions(accounts):
    client, sent = accounts
    register(client, sent)
    assert (
        post(
            client, "account/email", {"email": "new@example.com", "current_password": PASSWORD}
        ).status_code
        == 202
    )
    token = sent[-1]["token"]
    assert client.get("/api/v1/auth/me").json()["email"] == "first@example.com"
    assert post(client, "auth/confirm-email", {"token": token}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        post(client, "auth/login", {"email": "new@example.com", "password": PASSWORD}).status_code
        == 200
    )
    assert post(client, "auth/confirm-email", {"token": token}).status_code == 400


def test_password_change_rejects_wrong_password_then_revokes(accounts):
    client, sent = accounts
    register(client, sent)
    assert (
        post(
            client, "account/password", {"current_password": "wrong", "password": PASSWORD}
        ).status_code
        == 400
    )
    assert (
        post(
            client,
            "account/password",
            {"current_password": PASSWORD, "password": "Another private passphrase"},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_revoke_individual_and_all_sessions(accounts):
    client, sent = accounts
    register(client, sent)
    with TestClient(app, headers=HEADERS) as second:
        post(second, "auth/login", {"email": "first@example.com", "password": PASSWORD})
        sessions = client.get("/api/v1/account/sessions").json()
        other = next(row for row in sessions if not row["current"])
        response = client.delete(
            f"/api/v1/account/sessions/{other['id']}", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200
        assert second.get("/api/v1/auth/me").status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 200
        post(client, "account/logout-all")
        assert client.get("/api/v1/auth/me").status_code == 401


def test_rate_limit_survives_failed_login_and_resend(accounts):
    client, sent = accounts
    body = {"email": "nobody@example.com", "password": "incorrect password"}
    for _ in range(10):
        assert post(client, "auth/login", body).status_code == 401
    response = post(client, "auth/login", body)
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    assert post(client, "auth/resend-verification", {"email": "new@example.com"}).status_code == 202
    assert post(client, "auth/resend-verification", {"email": "new@example.com"}).status_code == 429


def test_delivery_failure_rolls_back_account_and_allows_retry(accounts, monkeypatch):
    client, sent = accounts

    def fail(*args):
        raise HTTPException(503, "Email unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("app.accounts.mail.send_link", fail)
        response = post(
            client, "auth/register", {"name": "A", "email": "a@example.com", "password": PASSWORD}
        )
        assert response.status_code == 503
    with Session(engine()) as db:
        assert db.scalar(select(User)) is None
        assert db.scalar(select(Workspace)) is None
    clear_limits()
    register(client, sent, "a@example.com")


def test_disabled_account_cannot_use_session_or_login(accounts):
    client, sent = accounts
    account = register(client, sent)
    with Session(engine()) as db, db.begin():
        db.get(User, UUID(account["id"])).active = False
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        post(client, "auth/login", {"email": "first@example.com", "password": PASSWORD}).status_code
        == 401
    )
