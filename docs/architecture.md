# Architecture and engineering decisions

## Implemented in increment 1

One repository contains a Python/FastAPI backend and React/TypeScript/Vite frontend.
The local preview API serves a fixed, checked-in public NOAA example and builds
query plans against its metadata snapshot. It never runs scientific work from an
HTTP request. The explicit CLI downloads and processes bounded source subsets.

The query planner, connector, and scientific calculation are separate modules with
Pydantic contracts. Frontend types are generated from OpenAPI. Billing and AI result
interpretation remain roadmap capabilities; accounts and persistence were added in increment 2, and
plans/usage accounting in increment 3.

## Implemented in increment 2

PostgreSQL/Alembic now persist accounts, personal workspaces, sessions, single-use
email tokens and shared authentication rate limits. The account module supports
verified registration, profile/security changes, recovery and owner-scoped access.
The frontend includes account forms and active-session management. Compose adds
a local PostgreSQL database, migration step and Mailpit inbox. See
[account architecture](accounts.md) for transaction and security semantics.

## Target architecture

Increment 3 persists free plans, default registration assignments, workspace access
status, analysis reservations, usage events and separate processing expenses. Plan
administration and the member usage page are available; increment 4 connects these
to durable execution.
The worker must call the internal entitlement service within the job transaction.
See [plan and usage contracts](plans-and-usage.md).

A modular monolith with a separate worker and PostgreSQL-backed job queue.
Increment 4 uses SKIP LOCKED claims, renewable leases and attempt fencing, with
shared private filesystem storage on the development server. Result publication
and usage settlement share one transaction. The storage adapter can later target
object storage if the deployment requires multiple hosts. No Redis/Celery service
is needed for this first bounded workload. See [durable analyses](durable-analyses.md).

Use PostgreSQL in development, tests, and production once persistence is introduced.
Use SQLAlchemy/Alembic; migrations are versioned and checked in CI. Do not develop
against SQLite and discover different concurrency semantics at launch.

### Shared platform responsibilities

Accounts/workspaces and ownership; plans/subscriptions and entitlement enforcement;
immutable analysis runs and stage history; artifact storage/retention; source and
method provenance; structured logging, diagnostics, and cost/usage tracking.

### Extension boundaries

1. Source connectors describe/query/fetch provider data and declare capabilities.
2. Domain modules own terminology, scientific operations, validation, and caveats.
3. Processing/rendering modules handle typed tables, time series, grids, and later
   other structures. Do not require latitude/longitude on every future dataset.

The SST implementation is domain-specific. Do not treat its Pydantic models as a
universal scientific ontology. Introduce a small shared envelope when a second
real data shape demonstrates the need.

## AI boundary

Guided planning now implements this boundary with a separate `copilot` module:
owner-scoped, idempotent planning records; one bounded structured-output call;
application-built proposals; daily request/budget admission; and estimated provider
cost settlement. Saving a reviewed proposal creates a normal saved analysis, never
a run. Existing execution remains the sole scientific/allowance path. See
[guided planning](guided-planning.md) for configuration and evaluation.

AI proposes structured intent, selects among eligible registered capabilities,
asks clarifying questions, and explains computed outputs. Application code validates
metadata, builds requests, enforces limits, performs calculations, and renders charts.
Initial execution uses registered operations; arbitrary generated code is out of scope.

Treat external metadata as untrusted content. Restrict network destinations and
redirects, downloaded/decompressed bytes, cell counts, runtime, retry count, and AI
spend. A failed interpretation must not discard valid scientific outputs.

## Reuse decisions

The current Radar README was inspected on 2026-10-13. It documents PostgreSQL,
revocable sessions, a durable staged worker, and owner-scoped runs. Reuse these
patterns and selectively inspect code in the relevant increment; do not copy its
complete application or assume its authorization/billing choices fit this product.

Margin Protection's evidence-preserving imports and deterministic calculations
inform this product's immutable source artifacts and calculated outputs. Current
implementation must be inspected before any code is reused.

## Release process

Small PRs target `main`; Stepan reviews and merges. CI tests scientific calculations,
API contracts, frontend builds and main browser flows. Live source verification is
explicit and separate from deterministic CI. Production releases and paid-service
configuration follow their own acceptance gates; feature PRs do not deploy either.

## Hosted development testing

The development server uses the standalone `compose.development.yaml`: Caddy
serves compiled assets and proxies the API over HTTPS, with a tester password gate.
PostgreSQL and SMTP have no host ports, and Mailpit's inbox is loopback-only for
SSH access. Deployment takes a database dump before applying migrations. This
is an early development deployment to support testing, distinct from the paid
production launch gate. See [the runbook](development-deployment.md).
