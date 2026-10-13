# Saved analyses and durable runs

Increment 4 enables live NOAA OISST analyses for verified members. Natural-language
planning, AI interpretation, additional scientific sources and paid billing remain
later increments. No new credentials or paid services are required.

## Try it

1. Deploy normally, sign in and open **Your analyses**.
2. Create a query for the Canary Islands, 2020-01-01 to 2020-01-31. Saving/editing
   costs no allowance. Start a run and confirm its dates and one-unit reservation.
3. Reload or close the browser. Reopen the analysis and select its run history.
4. Inspect processing history, the monthly chart and coverage notes. Download
   CSV, provenance, metadata and original NetCDF subsets from your private run.
5. Edit the saved query. Previous runs retain their original title, dates, region,
   source metadata, method hash and software versions. Each deliberate new run
   reserves a new allowance unit; automatic retries keep the original reservation.
6. Cancel a queued or active run. An active cancellation releases allowance only
   after the worker stops the child, or bounded recovery fences an abandoned child.

NOAA coverage is checked freshly in the worker. A saved query or the free planner
does not promise that the provider currently serves those dates. Provider outages,
unsupported metadata changes, invalid source arrays and inadequate access are
shown explicitly. Scientifically valid results can contain withheld monthly values
when coverage is insufficient; the coverage notes explain this.

## Local worker

Full Docker Compose starts the worker automatically. If running the API/frontend
directly, open a third terminal in the **repository root**, using the same `.env`:

```powershell
.\.venv\Scripts\python.exe -m app.analyses.worker
```

Linux/macOS: `.venv/bin/python -m app.analyses.worker`. API and worker must share the
same absolute `SDC_ARTIFACT_DIR` if their working directories differ. The default
is `artifacts/runs` relative to the working directory. Stop with Ctrl+C. Do not
start an additional container worker using a different artifact directory while
running a native API; use one consistent storage location.

## Transactions, leases and retries

PostgreSQL is the queue, not merely an eventual copy of a broker. Submission
authorizes ownership, checks the saved-query version and connector bounds, reserves
allowance and inserts an immutable run in **one transaction**. A client-generated
UUID makes repeat HTTP submissions idempotent; a different analysis/version under
the same UUID is rejected. Editing never mutates an existing run.

Workers use `FOR UPDATE SKIP LOCKED` and lock membership before run/reservation.
Each worker processes one child at a time; multiple workers require the same shared
artifact storage. This uses the [PostgreSQL queue-consumer locking pattern](https://www.postgresql.org/docs/17/sql-select.html).
No Redis or Celery is needed for the initial single-server workload.

- Each attempt has a fresh fencing token, 45-second renewable lease, and a hard
  ten-minute child-process budget. The supervisor heartbeats about every two seconds.
- Recovery needs both an expired lease and the previous hard deadline plus 30-second
  grace. A lost heartbeat alone never refunds quota. A stale token cannot publish
  results or settle usage. Browser restarts have no effect on execution.
- Transient network/429/5xx failures and interrupted workers retry at most three
  attempts, retaining the reservation; backoff is 10 then 20 seconds. Contract,
  coverage and deterministic processing errors fail without automatic retries.
- A graceful worker stop terminates its child and requeues the run within this
  same attempt budget. Hard crashes become recoverable within roughly 11 minutes.
- Successful result publication and quota consumption commit together. Failure or
  confirmed cancellation releases quota in the terminal-state transaction. Result
  files from an uncommitted or stale attempt are never exposed by the API.

The run's input snapshot is immutable; state and append-only stage events evolve.
Execution guarantees one published result and one usage settlement, not exactly one
provider download. A crash can cause a bounded repeat of read-only source requests.

## Bounds, storage and retention

Only the registered HTTPS NOAA metadata and OISST NetCDF endpoint are reachable
through the worker transport. Redirects and compressed HTTP responses are rejected.
Limits: 256 KB metadata, 16 MB per subset, 64 MB total subsets, two million cell-time
values, at most 3,663 days, and ten minutes per attempt. The Linux scientific child
has a 1.5 GiB address-space cap; the server worker container also has memory/process
limits. Downloads are split into yearly chunks; no user-supplied URLs or code execute.

The private `analysis-artifacts` volume is writable by the worker and mounted
read-only in the API. Attempt UUID directories are separate. Publication records
a manifest of checksums, sizes and media types; authenticated, owner-scoped exports
verify those checksums. Administrators cannot read another member's results.
The web server never serves this volume directly. Keep the volume with the database
when moving/restoring this environment; a database dump alone does not contain files.

Retention is snapshotted at admission and counted from terminal completion. Exports
deny access at expiry even while the worker is offline. Each worker cycle performs
due cleanup at least once per minute when idle; a running job may defer physical
cleanup until it finishes. Run history, checksums and usage records remain. Orphaned
attempt directories are removed after 24 hours; an active or published attempt is
preserved. Low disk space fails a run clearly rather than filling the volume.

Successful runs retain measured elapsed time/downloaded bytes in `timing.json`.
NOAA requires no paid provider key. No invented dollar expense is written for shared
server compute; the existing expense ledger remains available when an attributable
provider or compute price is introduced. Quota is not a measure of actual expense.

The UI lists up to 100 saved analyses per workspace, 25 runs per history page, and
up to 100 stage events per run. Saved analyses are edited, not deleted, in this
increment so accepted runs and their accounting stay traceable.

## Server deployment and diagnostics

The normal deployment builds the worker, backs up PostgreSQL, stops the API/worker
before migration, applies `0003_analyses`, and starts both with health checks. The
artifact volume is preserved. The worker has outbound access to NOAA; PostgreSQL
and the worker have no published ports. Existing account/plan/gateway configuration
continues to apply.

```bash
bash deploy/development/compose.sh ps
bash deploy/development/compose.sh logs --tail=100 worker
bash deploy/development/compose.sh exec worker python -m app.analyses.worker --health
```

To exercise restart recovery in development, start a run then restart `worker`.
Confirm the same run ID returns to progress, and usage ends with one completion or
one release. Do not manually refund a reservation merely because its worker stopped.

CI uses PostgreSQL and real child processes with retained NOAA bytes replacing only
HTTP transport. The fixture lives under `backend/tests`; there is no production
fixture flag or endpoint. Tests cover admission rollback/retries, stale edits,
competing claims, lease recovery/fencing, cancellation, private exports, checksum
damage, expiry cleanup and desktop/mobile journeys. Live-source acceptance is a
separate, explicit test after deployment so CI does not depend on NOAA availability.
