import os
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import settings
from app.db import engine
from app.main import app
from app.sst.contracts import AnalysisRequest
from app.sst.erddap import plan_query

HEADERS = {"Origin": "http://127.0.0.1:5173", "X-SDC-Request": "1"}


@pytest.fixture
def metadata():
    return files("app").joinpath("data/metadata.json").read_bytes()


@pytest.fixture
def plan(metadata):
    return plan_query(
        AnalysisRequest(start="2020-01-01", end="2020-01-31"),
        metadata,
        datetime(2026, 10, 13, tzinfo=UTC),
    )


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
