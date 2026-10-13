from datetime import UTC, datetime
from importlib.resources import files

import pytest

from app.sst.contracts import AnalysisRequest
from app.sst.erddap import plan_query


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
