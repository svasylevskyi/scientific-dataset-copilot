# Scientific Dataset Copilot

A **self-service, subscription-based SaaS** for discovering, querying, visualizing,
and explaining open scientific datasets. Ocean/climate is the first domain;
NOAA OISST sea-surface temperature is the first verified workflow.

## Current increment

This first increment provides a real NOAA reference analysis, deterministic SST
processing, a bounded live verification CLI, and a React/FastAPI local preview.
The preview displays the frozen 2016–2025 Canary Islands result, downloads its
CSV/chart/provenance, and previews queries for two named regions.

**This is a local development preview, not a launch-ready subscription service.**
Registration, login, persistent user analyses, job execution from the browser,
AI assistance, subscriptions, and billing are not implemented yet. They are
required milestones in the [self-service SaaS roadmap](docs/roadmap.md).
The API does not accept arbitrary URLs, perform live provider calls, or incur AI
charges. The explicitly invoked CLI is the only live data retrieval entry point.

## Local setup

Development runtimes: **Python 3.14.7 and Node.js 26.6.0**, recorded in
`.python-version` and `.node-version`. CI reads these files and runs the backend,
frontend, and browser checks on both Linux and Windows. Docker uses the same
versions; update its base images when changing the version files. Package metadata
keeps its existing compatibility floors, but these are the actively tested runtimes.
No API keys, paid services, database, or Stripe setup are needed for this increment.

Run the following commands from the cloned repository folder. On Windows, do not
use `C:\Windows\System32` as your project directory.

### Windows PowerShell

Confirm `python --version` reports 3.14.7 and `node --version` reports v26.6.0.
Create a virtual environment and start the API:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e ./backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

If `.venv` was created with another Python version, stop processes using it and
recreate that environment with Python 3.14.7 before installing dependencies.
Calling its interpreter directly avoids needing PowerShell script activation.

In a second PowerShell window, also in the repository folder:

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run dev
```

### Linux / macOS

With the documented Python and Node.js versions selected, from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.lock
python -m pip install --no-deps --no-build-isolation -e ./backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. API documentation: <http://localhost:8000/docs>.
Vite proxies `/api` to the local API; there is no cross-origin token setup.
`API_PROXY_TARGET` can change the development proxy target.

### Docker Compose

Alternatively, with Docker running (Linux containers on Windows):

```bash
docker compose up --build
```

Both published ports bind to loopback. This Compose file runs the development
preview; do not expose it publicly as a paid service.
Stop the app with Ctrl+C, then run `docker compose down` to remove its containers.

## Run a live reference analysis

With the virtual environment activated, from the repository root:

```bash
python -m app.sst.cli --region canaries --start 2016-01-01 --end 2025-12-31 --output artifacts/my-canaries-run
```

The output directory must not already exist. It contains the exact metadata,
query plan, raw NetCDF subsets, checksums, monthly CSV, analysis JSON, and timing.
`--region madeira` is also supported. Every run inspects fresh metadata and rejects
dates outside available coverage. Provider failures are reported, never replaced
with synthetic data. Partial files remain for inspection after failure; use a new
output directory for a retry.

The web example remains frozen: running this command does not update its chart.
See [scientific methodology and provenance](docs/scientific-method.md) and
[reference verification](docs/reference-verification.md) for results and limitations.

## Verification

```bash
python -m pytest backend/tests -q
python -m ruff check backend
python -m ruff format --check backend
python backend/scripts/export_openapi.py
npm --prefix frontend run api:types
npm --prefix frontend run build
```

With the virtual environment activated, browser checks start the local API/frontend
and exercise both viewport sizes (or reuse already-running local servers):

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

The verification commands above assume the virtual environment is activated.
In PowerShell, Python-only checks can instead use `.\.venv\Scripts\python.exe`
in place of `python`; use `npm.cmd` / `npx.cmd` for Node.js commands. For browser
checks, ensure that the virtual environment's `Scripts` directory is on `PATH`,
because Playwright launches the API using `python`.

Normal tests use synthetic analytic cases and the checked-in NOAA snapshot; they
do not access NOAA, an AI provider, or Stripe. CI checks generated API contract
drift and the same backend/build/browser checks. Python dependencies are pinned
in `backend/requirements.lock`; JavaScript dependencies in `frontend/package-lock.json`.

## Project layout

| Path | Purpose |
| --- | --- |
| `backend/app/sst` | First domain's validated connector, query planner, scientific processing, CLI |
| `backend/app/data` | Frozen public-source example and metadata |
| `backend/app/main.py` | Network-free local preview API |
| `backend/tests` | Scientific correctness, connector, and API checks |
| `frontend` | React/TypeScript interface, generated API types, browser checks |
| `docs` | Product decisions, roadmap, architecture, and scientific methods |

The repository is the source of truth for accepted decisions. Work proceeds in
feature branches and PRs; Stepan reviews and merges. See [architecture](docs/architecture.md).
