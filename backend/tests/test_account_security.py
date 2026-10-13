"""Security checks that do not require a running database."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.accounts.schemas import RegisterInput
from app.accounts.security import digest, password_hasher, password_matches, secret
from app.config import settings
from app.main import app


def test_passwords_are_salted_and_tokens_have_no_plaintext_digest():
    first = password_hasher.hash("a long private passphrase")
    second = password_hasher.hash("a long private passphrase")
    assert first != second
    assert first.startswith("$argon2id$")
    assert password_matches("a long private passphrase", first)
    assert not password_matches("incorrect", first)
    token = secret()
    assert len(token) >= 40 and token not in digest(token)


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"verified": True}, {"owner_id": "123"}])
def test_signup_cannot_assign_privileges(extra):
    with pytest.raises(ValidationError):
        RegisterInput(email="a@example.com", name="A", password="long enough password", **extra)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://evil.example", "X-SDC-Request": "1"},
        {"Origin": "http://127.0.0.1:5173"},
    ],
)
def test_cross_site_writes_fail_before_database_access(headers):
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={
            "email": "a@example.com",
            "password": "long enough password",
        },
    )
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_missing_session_and_malformed_cookie_are_unauthorized():
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        client.cookies.set("sdc_session", "invalid")
        assert client.get("/api/v1/auth/me").status_code == 401


def test_public_deployment_requires_https_and_secure_cookies(monkeypatch):
    settings.cache_clear()
    monkeypatch.setenv("SDC_PUBLIC_URL", "http://copilot.example.com")
    with pytest.raises(ValueError, match="HTTPS"):
        settings()
    monkeypatch.setenv("SDC_PUBLIC_URL", "https://copilot.example.com")
    monkeypatch.setenv("SDC_SECURE_COOKIES", "true")
    assert settings().secure_cookies
    settings.cache_clear()
