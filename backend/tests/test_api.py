from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_reference_exports_and_query_preview_never_download(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Preview must not make provider requests")

    monkeypatch.setattr("app.sst.erddap.fetch_bytes", unexpected)
    response = client.get("/api/v1/reference")
    assert response.status_code == 200
    data = response.json()
    assert data["source_kind"] == "live_noaa"
    assert len(data["months"]) == 120
    assert client.get("/api/v1/reference.csv").headers["content-type"].startswith("text/csv")
    assert "attachment" in client.get("/api/v1/reference.json").headers["content-disposition"]
    response = client.post(
        "/api/v1/query-preview",
        json={
            "region_id": "madeira",
            "start": "2020-01-01",
            "end": "2020-12-31",
        },
    )
    assert response.status_code == 200
    assert response.json()["region"]["id"] == "madeira"
    catalog = client.get("/api/v1/catalog").json()
    assert catalog["capabilities"]["live_web_execution"] is True
    assert catalog["capabilities"]["subscriptions"] is False


def test_invalid_dates_and_unknown_inputs_return_422():
    for body in [
        {"start": "2099-01-01", "end": "2099-02-01"},
        {"start": "2020-02-01", "end": "2020-01-01"},
        {"start": "2020-01-01", "end": "2020-02-01", "url": "http://localhost"},
    ]:
        assert client.post("/api/v1/query-preview", json=body).status_code == 422


def test_health_is_explicit_about_local_preview():
    assert client.get("/api/v1/health").json() == {
        "status": "ok",
        "mode": "local-reference-preview",
    }
