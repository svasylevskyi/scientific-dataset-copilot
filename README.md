# Scientific Dataset Copilot

A **self-service, subscription-based SaaS** for discovering, querying, visualizing,
and explaining open scientific datasets. Ocean/climate is the first domain;
NOAA OISST sea-surface temperature is the first verified workflow.

## Current increment

The app provides a verified NOAA reference analysis and query planner, plus
persistent accounts and personal workspaces. Users can register, verify their
email, sign in, recover or change a password, update their profile/email, and
review or revoke sessions. Administrators manage free plans and account assignments;
members can view their plan and usage. Members can save NOAA queries, start durable
background analyses, inspect run history and export private results. A local email
inbox makes account flows testable.

**This is a local development app, not a launch-ready subscription service.**
AI assistance and paid billing follow in the [self-service SaaS roadmap](docs/roadmap.md).
The API persists jobs; a separate worker downloads bounded NOAA subsets and publishes
results. The free reference and planner remain available without running a job.
See [saved analyses and worker operation](docs/durable-analyses.md).

## Local setup

Development runtimes: **Python 3.14.7 and Node.js 26.6.0**, recorded in
`.python-version` and `.node-version`. CI reads these files and runs the backend,
frontend, and browser checks on both Linux and Windows. Docker uses the same
versions; update its base images when changing the version files. Package metadata
keeps its existing compatibility floors, but these are the actively tested runtimes.
Accounts require PostgreSQL. Docker Desktop (Linux containers on Windows) supplies
the database and Mailpit email inbox. No paid services or API keys are required.
PostgreSQL 17.11 and Mailpit 1.31.5 are pinned in Compose and the integration CI job.

Run the following commands from the cloned repository folder. On Windows, do not
use `C:\Windows\System32` as your project directory.

### Windows PowerShell

Confirm `python --version` reports 3.14.7 and `node --version` reports v26.6.0.
Start Docker Desktop, then prepare the dependencies and API. Existing `.venv`
users can keep their environment and rerun the installation commands:

```powershell
docker compose up -d --wait db mailpit
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m venv .venv
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e ./backend
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
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
docker compose up -d --wait db mailpit
test -f .env || cp .env.example .env
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.lock
python -m pip install --no-deps --no-build-isolation -e ./backend
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open **<http://127.0.0.1:5173>**. API documentation: <http://127.0.0.1:8000/docs>.
Email inbox: **<http://127.0.0.1:8025>**. Use the exact `127.0.0.1` application
origin configured in `.env`; `localhost` is a different origin for CSRF checks.
Vite proxies `/api` to the local API. Session cookies are HttpOnly and are never
stored in browser local storage.
`API_PROXY_TARGET` can change the development proxy target.

### Start the analysis worker

When running the API/frontend directly, start a third terminal in the repository
root with the same environment:

```powershell
.\.venv\Scripts\python.exe -m app.analyses.worker
```

On Linux/macOS use `.venv/bin/python -m app.analyses.worker`. Full Compose starts it
automatically. See [worker and storage details](docs/durable-analyses.md).

### Docker Compose

Alternatively, with Docker running (Linux containers on Windows):

```bash
docker compose up --build
```

Compose starts PostgreSQL, Mailpit, a one-shot migration service, the API, the
analysis worker and the frontend. All published ports bind to loopback; the credentials and mail inbox
are for local development only. Stop with Ctrl+C, then `docker compose down`.
Named PostgreSQL and artifact volumes preserve accounts and results across restarts. **Do not use
`docker compose down -v` unless you intend to delete the local database.**

### Try the complete account journey

1. Choose **Sign in → Create account**, using an address such as `explorer@example.com`.
2. Open Mailpit at <http://127.0.0.1:8025>, open the verification email, follow its
   link and press **Verify your email**. Mailpit captures messages locally; it does
   not deliver them to real mailboxes.
3. Sign in, update your name on **Your account**, reload and confirm it persists.
4. Sign out, use **Forgot password?**, then follow the reset email in Mailpit.
5. Sign in with the new password. Test email changes and session sign-out on the
   account page. Changing a password or confirming a new email revokes all sessions.

Resending the same kind of email has a 60-second cooldown. Verification links last
24 hours; password-reset and email-change links last 30 minutes. Links require an
explicit confirmation, so merely opening a URL does not consume it.

### Local administrator

First register and verify an ordinary account. Then explicitly grant its role:

```powershell
.\.venv\Scripts\python.exe -m app.accounts.cli promote explorer@example.com
```

For the full Compose setup use `docker compose exec api python -m app.accounts.cli
promote explorer@example.com` (on one line). Refresh the account page to see account
counts. `demote` reverses this role change. No default admin credentials are created.
Admin access does not grant access to another user's workspace. **Manage plans**
provides plan editing, registration defaults, archiving and account assignment.
**Plan and usage** shows the member's allowance and history. Migration `0002_plans`
assigns existing accounts to an editable free Development plan (20 monthly analyses,
one at a time). Live analyses use this allowance; reference previews use no quota.
See [plans and usage](docs/plans-and-usage.md) for policies and testing steps.

See [account architecture and configuration](docs/accounts.md) for SMTP settings,
session semantics and deployment boundaries.

## Hosted development environment

**Guided planning:** describe an SST request in **Your analyses**, clarify missing
details, review/edit the validated proposal, and save it before explicitly starting
a run. Optional OpenAI configuration, independent planning limits/costs, and live
evaluation instructions are in [guided planning](docs/guided-planning.md).
The manual form remains available without an AI key.

A separate Ubuntu/Hetzner setup is available with a compiled frontend, HTTPS,
a tester password gate, private PostgreSQL/SMTP and Mailpit through an SSH tunnel.
Follow [the development deployment guide](docs/development-deployment.md).
For manual deployments from GitHub Actions, complete the one-time
[GitHub deployment setup](docs/github-deployment.md), then use **Deploy development → Run workflow**.
It runs Docker Engine on the server; your Windows PC does not need Docker Desktop.
Use `deploy/development/compose.sh` for this environment; the root `compose.yaml`
continues to serve local development.

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
python -m pytest backend/tests -q -m "not postgres"
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

CI reports browser system dependencies, browser download, and test execution as
separate steps. System dependency installation runs only on Linux: the Windows
headless Chromium suite does not need the optional Media Foundation feature,
which previously added more than three minutes to each Windows job. Windows still
runs the complete scientific, API, frontend-build and reference-browser checks.
The development deployment job covers both a fresh install and an update while
the old gateway is running, followed by HTTPS and tester-gate browser checks.

CI limits browser installation to the headless shell, caps dependency/download
steps to 4 minutes, and gives the test suite 2 minutes to finish and report errors
before the 3-minute test-step limit. Download diagnostics and per-test progress
remain visible in the job log. Desktop and mobile coverage includes the account journey in a separate Linux job
with real PostgreSQL and Mailpit. The Linux/Windows matrix keeps the scientific,
API-security, build and reference-browser checks. Container smoke tests also check
the migrated database readiness endpoint.

### PostgreSQL integration checks

Tests truncate their database. Use a **separate disposable database whose name ends
in `_test`**; never use your local `sdc` database. From PowerShell, with dependencies
running and the backend installed:

```powershell
docker compose exec db createdb -U sdc sdc_test
$env:SDC_TEST_DATABASE_URL = "postgresql+psycopg://sdc:sdc_local@127.0.0.1:5432/sdc_test"
.\.venv\Scripts\python.exe -m pytest backend/tests/test_accounts.py -q
Remove-Item Env:SDC_TEST_DATABASE_URL
```

`createdb` is needed only once. The tests run migrations, compare model/schema drift,
exercise downgrade/upgrade, concurrent token use, isolation and persisted revocation.
On Linux/macOS export the same environment variable and use `.venv/bin/python`.

For browser account tests, use the migrated development database and Mailpit, set
`SDC_ACCOUNT_E2E=1` and run `npm run test:e2e -- accounts.spec.ts` from `frontend`.
In PowerShell set `$env:SDC_ACCOUNT_E2E = "1"` first. These tests create disposable
example.com accounts and send mail only to the configured SMTP service.

## Project layout

| Path | Purpose |
| --- | --- |
| `backend/app/sst` | First domain's validated connector, query planner, scientific processing, CLI |
| `backend/app/data` | Frozen public-source example and metadata |
| `backend/app/main.py` | Public preview and account API |
| `backend/app/accounts` | Authentication, email, workspace ownership, operator CLI |
| `backend/migrations` | Versioned PostgreSQL schema |
| `backend/tests` | Scientific correctness, connector, and API checks |
| `frontend` | React/TypeScript interface, generated API types, browser checks |
| `docs` | Product decisions, roadmap, architecture, and scientific methods |

The repository is the source of truth for accepted decisions. Work proceeds in
feature branches and PRs; Stepan reviews and merges. See [architecture](docs/architecture.md).
