import json
from datetime import UTC, datetime
from urllib.parse import unquote

import httpx
import pytest
from pydantic import ValidationError

from app.sst.contracts import AnalysisRequest, Bounds
from app.sst.erddap import METADATA_URL, SourceError, fetch_bytes, parse_metadata, plan_query


def test_ten_year_query_uses_every_day_and_inside_grid_centers(metadata):
    plan = plan_query(
        AnalysisRequest(start="2016-01-01", end="2025-12-31"), metadata, datetime.now(UTC)
    )
    assert len(plan.chunks) == 10
    assert plan.estimated_cells == 3653 * 12 * 24
    url = unquote(plan.chunks[0].url)
    assert "sst[(2016-01-01T12:00:00Z):1:(2016-12-31T12:00:00Z)]" in url
    assert "[(27.125):1:(29.875)][(341.125):1:(346.875)]" in url
    assert plan.selected_grid_bounds.west == -18.875


def test_coverage_is_rejected_not_silently_clipped(metadata):
    with pytest.raises(SourceError, match="available coverage"):
        plan_query(
            AnalysisRequest(start="2026-01-01", end="2027-01-01"), metadata, datetime.now(UTC)
        )


@pytest.mark.parametrize("start,end", [("2020-02-01", "2020-01-01"), ("2000-01-01", "2025-12-31")])
def test_invalid_or_excessive_dates(start, end):
    with pytest.raises(ValidationError):
        AnalysisRequest(start=start, end=end)


def test_unknown_regions_and_extra_execution_fields_are_rejected():
    with pytest.raises(ValidationError):
        AnalysisRequest(region_id="global", start="2020-01-01", end="2020-01-31")
    with pytest.raises(ValidationError):
        AnalysisRequest(start="2020-01-01", end="2020-01-31", url="http://localhost")


@pytest.mark.parametrize(
    "changes", [{"east": -20}, {"east": 1}, {"north": 50}, {"south": float("nan")}]
)
def test_unsupported_bounds(changes):
    with pytest.raises(ValidationError):
        Bounds(**({"west": -19, "east": -13, "south": 27, "north": 30} | changes))


@pytest.mark.parametrize(
    "variable,attribute,value",
    [
        ("sst", "units", "kelvin"),
        ("sst", "standard_name", "air_temperature"),
        ("NC_GLOBAL", "product_version", "3.0"),
        ("longitude", "actual_range", "-180, 180"),
    ],
)
def test_metadata_contract_changes_fail_closed(metadata, variable, attribute, value):
    data = json.loads(metadata)
    for row in data["table"]["rows"]:
        if row[1:3] == [variable, attribute]:
            row[4] = value
    with pytest.raises(SourceError):
        parse_metadata(json.dumps(data).encode())


def test_transport_caps_bytes_and_does_not_follow_redirects():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"12345"))
    ) as client:
        with pytest.raises(SourceError, match="download limit"):
            fetch_bytes(client, METADATA_URL, 4)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"Location": "http://127.0.0.1"})
        )
    ) as client:
        with pytest.raises(SourceError, match="request failed"):
            fetch_bytes(client, METADATA_URL, 100)


def test_unregistered_destinations_never_reach_transport():
    def unexpected(_):
        pytest.fail("Unregistered URL reached transport")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(SourceError, match="registered NOAA"):
            fetch_bytes(client, "http://169.254.169.254/", 100)


def test_provider_failure_is_reported_without_automatic_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="request failed"):
            fetch_bytes(client, METADATA_URL, 100)
    assert len(calls) == 1
