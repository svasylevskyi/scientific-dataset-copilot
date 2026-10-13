"""Explicit live verification command; never runs on server startup or in normal CI."""

import argparse
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from time import monotonic

import httpx

from app.sst.contracts import REGIONS, AnalysisRequest, AnalysisResult, RawArtifact
from app.sst.erddap import (
    MAX_CHUNK_BYTES,
    MAX_METADATA_BYTES,
    MAX_TOTAL_BYTES,
    METADATA_URL,
    SourceError,
    fetch_bytes,
    plan_query,
    sha256,
    write_new,
)
from app.sst.processing import aggregate, load_subset, method_sha256, monthly_csv, runtime_versions


def revision() -> str:
    try:
        root = Path(__file__).resolve().parents[3]
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        ).strip()
        return value + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run(request: AnalysisRequest, output: Path) -> AnalysisResult:
    output.mkdir(parents=True, exist_ok=False)
    start_time = monotonic()
    timeout = httpx.Timeout(60, connect=10)
    with httpx.Client(
        timeout=timeout, headers={"User-Agent": "ScientificDatasetCopilot/0.1"}
    ) as client:
        raw_metadata = fetch_bytes(client, METADATA_URL, MAX_METADATA_BYTES)
        fetched_at = datetime.now(UTC)
        write_new(output / "metadata.json", raw_metadata)
        plan = plan_query(request, raw_metadata, fetched_at)
        write_new(output / "plan.json", plan.model_dump_json(indent=2).encode())
        artifacts = []
        arrays = []
        total_bytes = 0
        for i, chunk in enumerate(plan.chunks):
            if monotonic() - start_time > 600:
                raise SourceError("Run exceeded the ten-minute budget; retained partial artifacts.")
            print(f"Fetching {chunk.start} to {chunk.end}", file=sys.stderr, flush=True)
            started = monotonic()
            raw = fetch_bytes(
                client, chunk.url, min(MAX_CHUNK_BYTES, MAX_TOTAL_BYTES - total_bytes)
            )
            duration = monotonic() - started
            total_bytes += len(raw)
            name = f"subset-{i + 1:02}.nc"
            path = output / name
            write_new(path, raw)
            artifacts.append(
                RawArtifact(
                    file=name,
                    sha256=sha256(raw),
                    bytes=len(raw),
                    query_url=chunk.url,
                    duration_seconds=round(duration, 3),
                )
            )
            arrays.append(load_subset(path, plan, chunk))
    result = AnalysisResult(
        plan=plan,
        created_at=datetime.now(UTC),
        source_kind="live_noaa",
        artifacts=artifacts,
        runtime_versions=runtime_versions(),
        source_revision=revision(),
        method_sha256=method_sha256(),
        **aggregate(arrays, plan),
    )
    write_new(output / "analysis.json", result.model_dump_json(indent=2).encode())
    write_new(output / "monthly.csv", monthly_csv(result.months).encode())
    write_new(
        output / "timing.json",
        json.dumps(
            {
                "elapsed_seconds": round(monotonic() - start_time, 3),
                "downloaded_bytes": total_bytes,
            },
            indent=2,
        ).encode(),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=list(REGIONS), default="canaries")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--output", required=True, type=Path, help="New directory; never overwritten"
    )
    args = parser.parse_args()
    try:
        result = run(
            AnalysisRequest(region_id=args.region, start=args.start, end=args.end), args.output
        )
    except (ValueError, OSError) as exc:
        parser.exit(
            1, f"Reference run failed: {exc}\nPartial artifacts, if any, remain in {args.output}\n"
        )
    print(f"Saved {len(result.months)} monthly results to {args.output}")


if __name__ == "__main__":
    main()
