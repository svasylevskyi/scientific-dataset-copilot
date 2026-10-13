"""Public scientific preview plus persistent, isolated user accounts."""

import json
from importlib.resources import files

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.accounts.models import User
from app.accounts.routes import Db
from app.accounts.routes import router as accounts_router
from app.sst.contracts import REGIONS, AnalysisRequest, AnalysisResult, QueryPlan
from app.sst.erddap import SourceError, plan_query
from app.sst.processing import monthly_csv

app = FastAPI(title="Scientific Dataset Copilot", version="0.2.0")
app.include_router(accounts_router)


@app.exception_handler(OperationalError)
async def database_unavailable(request, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "Account storage is unavailable. Please try again shortly."},
    )


@app.middleware("http")
async def account_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(
        ("/api/v1/auth", "/api/v1/account", "/api/v1/workspaces", "/api/v1/admin")
    ):
        response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def reference() -> AnalysisResult:
    raw = files("app").joinpath("data/reference.json").read_text()
    return AnalysisResult.model_validate_json(raw)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "local-reference-preview"}


@app.get("/api/v1/ready")
def ready(db: Db):
    db.execute(select(User.id).limit(1))
    return {"status": "ready"}


@app.get("/api/v1/catalog")
def catalog():
    result = reference()
    return {
        "source": result.plan.source,
        "metadata_fetched_at": result.plan.metadata_fetched_at,
        "regions": list(REGIONS.values()),
        "capabilities": {
            "query_preview": True,
            "reference_chart": True,
            "live_web_execution": False,
            "natural_language": False,
            "accounts": True,
            "subscriptions": False,
        },
    }


@app.post("/api/v1/query-preview", response_model=QueryPlan)
def query_preview(request: AnalysisRequest):
    raw = files("app").joinpath("data/metadata.json").read_bytes()
    try:
        return plan_query(request, raw, reference().plan.metadata_fetched_at)
    except SourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/reference", response_model=AnalysisResult)
def get_reference():
    return reference()


@app.get("/api/v1/reference.csv")
def export_reference():
    return Response(
        monthly_csv(reference().months),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="canaries-sst-reference.csv"'},
    )


@app.get("/api/v1/reference.json")
def export_provenance():
    return Response(
        json.dumps(reference().model_dump(mode="json"), indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="canaries-sst-provenance.json"'},
    )
