"""Disposable scientific child process. It has no database or publication rights."""

import argparse
import json
import os
import shutil
import threading
from pathlib import Path

from app.analyses.service import RUN_SECONDS
from app.analyses.source import TransientSourceError, fetch_bytes
from app.sst.cli import run
from app.sst.contracts import AnalysisRequest
from app.sst.erddap import SourceError


def write_status(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--status", required=True, type=Path)
    args = parser.parse_args()
    if os.name == "posix":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
    history = []

    def report(stage, message):
        history.append({"stage": stage, "message": message})
        write_status(args.status, {"stage": stage, "message": message, "history": history})

    watchdog = threading.Timer(RUN_SECONDS, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    try:
        if shutil.disk_usage(args.output.parent).free < 256_000_000:
            raise SourceError("Artifact storage is nearly full. Contact an administrator.")
        run(
            AnalysisRequest.model_validate_json(args.request),
            args.output,
            fetcher=fetch_bytes,
            progress=report,
        )
        write_status(
            args.status, {"stage": "ready", "message": "Results computed.", "history": history}
        )
    except (SourceError, OSError, ValueError) as exc:
        message = (
            str(exc)
            if isinstance(exc, SourceError)
            else "Scientific processing or artifact storage failed."
        )
        write_status(
            args.status,
            {
                "stage": "failed",
                "message": message[:500],
                "retry": isinstance(exc, TransientSourceError),
                "history": history,
            },
        )
        raise SystemExit(1) from exc
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    main()
