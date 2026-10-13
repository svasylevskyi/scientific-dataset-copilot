"""One bounded child at a time; PostgreSQL is the durable queue and state authority."""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from time import monotonic, time

from sqlalchemy.orm import Session

from app.analyses import storage
from app.analyses.service import RUN_SECONDS, claim, finish, heartbeat
from app.db import engine

log = logging.getLogger("sdc.worker")
STOP = threading.Event()
HEALTH = Path(tempfile.gettempdir()) / "sdc-worker-heartbeat"


def status_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def stop_child(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def execute(job, *, pipeline_command: list[str] | None = None):
    directory = storage.attempt_path(job.id, job.lease_token)
    directory.parent.mkdir(parents=True, exist_ok=True)
    status = directory.parent / f"{job.lease_token}.status.json"
    environment = os.environ | {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
    child = None
    seen = 0
    progress = {}
    started = monotonic()
    outcome, message, retry, artifacts = "failed", "Worker process failed.", False, None
    try:
        child = subprocess.Popen(
            (pipeline_command or [sys.executable, "-m", "app.analyses.pipeline"])
            + [
                "--request",
                json.dumps(job.query),
                "--output",
                str(directory),
                "--status",
                str(status),
            ],
            env=environment,
        )
        while True:
            progress = status_file(status)
            with Session(engine()) as db, db.begin():
                decision = heartbeat(
                    db,
                    job.id,
                    job.workspace_id,
                    job.lease_token,
                    [
                        (item["stage"], item["message"])
                        for item in progress.get("history", [])[seen:]
                    ],
                )
            seen = len(progress.get("history", []))
            HEALTH.touch()
            if decision == "lost":
                # A stale attempt must never publish or settle usage.
                return
            if decision == "cancel":
                outcome, message = "cancelled", "Cancelled; allowance released."
                break
            if STOP.is_set():
                retry, message = True, "Worker stopped during deployment."
                break
            if monotonic() - started >= RUN_SECONDS:
                message = "The analysis exceeded its ten-minute time budget."
                break
            if child.poll() is not None:
                progress = status_file(status)
                if child.returncode == 0:
                    artifacts = storage.manifest(job.id, job.lease_token, job.query)
                    outcome, message = (
                        "succeeded",
                        "Results published; one allowance unit completed.",
                    )
                else:
                    message = progress.get("message", "Scientific worker stopped unexpectedly.")
                    retry = progress.get("retry", child.returncode not in {1, 124})
                break
            STOP.wait(2)
    except Exception:
        log.exception("Attempt failed run=%s attempt=%s", job.id, job.attempt)
        # Errors in persistence/publication are retried under the original reservation.
        message, retry = "Worker or artifact publication failed.", True
    finally:
        if child is not None:
            stop_child(child)
        progress = status_file(status)
        status.unlink(missing_ok=True)
    with Session(engine()) as db, db.begin():
        heartbeat(
            db,
            job.id,
            job.workspace_id,
            job.lease_token,
            [(item["stage"], item["message"]) for item in progress.get("history", [])[seen:]],
        )
        finish(
            db,
            job.id,
            job.workspace_id,
            job.lease_token,
            outcome=outcome,
            message=message,
            retry=retry,
            artifacts=artifacts,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process at most one eligible run")
    parser.add_argument(
        "--health", action="store_true", help="Check this container's worker heartbeat"
    )
    args = parser.parse_args()
    if args.health:
        raise SystemExit(0 if HEALTH.exists() and time() - HEALTH.stat().st_mtime < 60 else 1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    storage.root().mkdir(parents=True, exist_ok=True)
    cleanup_at = 0
    while not STOP.is_set():
        try:
            if monotonic() >= cleanup_at:
                with Session(engine()) as db, db.begin():
                    storage.cleanup(db)
                    storage.cleanup_orphans(db)
                cleanup_at = monotonic() + 60
            with Session(engine(), expire_on_commit=False) as db, db.begin():
                job = claim(db)
            HEALTH.touch()
            if job:
                log.info("Processing run=%s attempt=%s", job.id, job.attempt)
                execute(job)
            if args.once:
                return
            if not job:
                STOP.wait(2)
        except Exception:
            log.exception("Worker cycle failed; durable runs remain recoverable")
            if args.once:
                raise
            STOP.wait(5)


if __name__ == "__main__":
    main()
