"""Private local artifact adapter. Only database-published files are downloadable."""

import os
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analyses.models import AnalysisRun
from app.analyses.service import TERMINAL, clock, locked_run
from app.sst.contracts import AnalysisRequest, AnalysisResult
from app.sst.erddap import MAX_CHUNK_BYTES, MAX_TOTAL_BYTES, sha256


def root() -> Path:
    return Path(os.getenv("SDC_ARTIFACT_DIR", "artifacts/runs")).resolve()


def safe_path(relative: str) -> Path:
    path = (root() / relative).resolve()
    if not path.is_relative_to(root()) or path == root():
        raise ValueError("Invalid artifact path")
    return path


def attempt_path(run_id: UUID, token: UUID) -> Path:
    return safe_path(f"{run_id}/{token}")


def manifest(run_id: UUID, token: UUID, query: dict) -> list[dict]:
    directory = attempt_path(run_id, token)
    result = AnalysisResult.model_validate_json((directory / "analysis.json").read_bytes())
    if (
        result.plan.request != AnalysisRequest.model_validate(query)
        or result.source_kind != "live_noaa"
    ):
        raise ValueError("Result does not match the accepted run")
    names = {
        "analysis.json": "application/json",
        "plan.json": "application/json",
        "metadata.json": "application/json",
        "timing.json": "application/json",
        "monthly.csv": "text/csv",
    }
    if len(result.artifacts) != len(result.plan.chunks) or len(result.artifacts) > 11:
        raise ValueError("Unexpected source artifact count")
    for index, artifact in enumerate(result.artifacts):
        name = f"subset-{index + 1:02}.nc"
        if artifact.file != name:
            raise ValueError("Unexpected source artifact name")
        names[name] = "application/x-netcdf"
    rows = []
    total = 0
    for name, media_type in names.items():
        path = directory / name
        if path.stat().st_size > MAX_CHUNK_BYTES:
            raise ValueError("Artifact exceeds the size limit")
        content = path.read_bytes()
        total += len(content)
        digest = sha256(content)
        if name == "metadata.json" and digest != result.plan.metadata_sha256:
            raise ValueError("Metadata checksum mismatch")
        original = next((item for item in result.artifacts if item.file == name), None)
        if original and (original.sha256 != digest or original.bytes != len(content)):
            raise ValueError("Source checksum mismatch")
        rows.append(
            dict(
                name=name,
                relative_path=f"{run_id}/{token}/{name}",
                media_type=media_type,
                sha256=digest,
                bytes=len(content),
            )
        )
    if total > MAX_TOTAL_BYTES + 2_000_000:
        raise ValueError("Artifact set exceeds the total limit")
    return rows


def read_artifact(artifact) -> bytes:
    try:
        path = safe_path(artifact.relative_path)
        if path.stat().st_size != artifact.bytes:
            raise ValueError("Artifact size mismatch")
        content = path.read_bytes()
        if sha256(content) != artifact.sha256:
            raise ValueError("Artifact checksum mismatch")
        return content
    except (OSError, ValueError) as exc:
        raise HTTPException(
            503, "This result file is unavailable or damaged. Contact an administrator."
        ) from exc


def cleanup(db: Session) -> int:
    """Idempotent expiry cleanup; metadata and allowance history are retained."""
    moment = clock(db)
    expired = db.execute(
        select(AnalysisRun.id, AnalysisRun.workspace_id)
        .where(
            AnalysisRun.status.in_(TERMINAL),
            AnalysisRun.expires_at <= moment,
            AnalysisRun.purged_at.is_(None),
        )
        .order_by(AnalysisRun.expires_at)
        .limit(50)
    ).all()
    for run_id, workspace_id in expired:
        run = locked_run(db, run_id, workspace_id)
        directory = safe_path(str(run_id))
        if directory.exists():
            shutil.rmtree(directory)
        run.purged_at = moment
    return len(expired)


def cleanup_orphans(db: Session) -> None:
    # Failed attempt directories never become public. Remove them after 24h;
    # retain the published attempt until its original retention date.
    if not root().exists():
        return
    threshold = clock(db).timestamp() - 86400
    for run_dir in root().iterdir():
        if not run_dir.is_dir() or run_dir.is_symlink():
            continue
        try:
            run_id = UUID(run_dir.name)
        except ValueError:
            continue
        run = db.get(AnalysisRun, run_id)
        for directory in run_dir.iterdir():
            if (
                not directory.is_dir()
                or directory.is_symlink()
                or directory.stat().st_mtime >= threshold
            ):
                continue
            if (
                run
                and str(run.lease_token) == directory.name
                and (run.status == "running" or (run.status == "succeeded" and not run.purged_at))
            ):
                continue
            shutil.rmtree(directory)
