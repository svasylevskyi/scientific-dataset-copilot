# Implementation roadmap

The first commercial release is self-service SaaS. A local reference preview is an
engineering milestone, not a change to the business model.

| Increment | Scope | Acceptance gate |
| --- | --- | --- |
| 1 — Scientific reference and foundation | Verified OISST connector, explicit region/date contracts, deterministic aggregation, provenance, React/FastAPI preview, CI and setup | Independent numerical reference agrees; insufficient coverage is visible; exports work |
| 2 — Accounts and persistence | PostgreSQL/Alembic, personal workspaces, verified registration, login/logout, rotating/revocable sessions, recovery, user/admin scopes | A user can independently join, return, and manage their account; isolation and session lifecycle tests pass |
| 3 — Plans and entitlement foundation | Database-managed plans, admin editing, usage ledger and atomic reservations, subscription status, price mappings | Concurrent requests cannot overspend allowance; UI and API agree on access; policies for failure/cancellation/retry are explicit |
| 4 — Durable user analysis | Saved analyses and immutable runs, separate worker, bounded downloads, stage history, leases/recovery, artifact retention and owner-scoped exports | Runs survive worker/browser restarts; retries do not duplicate results or usage; no unbounded requests |
| 5 — Copilot workflow | Typed natural-language intent, supported-source selection, editable plan, clarification, grounded interpretation and evaluation suite | Correct dataset/units/dates/region handling across representative prompts; numeric claims are supported by computed results |
| 6 — Self-service checkout | Stripe sandbox checkout and customer portal, signed/idempotent webhooks, reconciliation, payment-dependent activation and clear cancellation behavior | Signup → payment → analysis → renewal/cancellation/failure flows pass end to end before live mode |
| 7 — Paid launch gate | Production deployment and recovery drill, rate limits, diagnostics, usage/cost visibility, policies, support, landing/onboarding, live billing verification | A new customer can complete the full journey independently; production acceptance checklist is complete |

Plan limits are enforced before dispatch, not merely in the browser. Reserve usage
atomically, reconcile on terminal job state, and distinguish customer quota from
actual provider/compute expense. Trial or default registration plans must not
accidentally grant unpaid access to a mapped paid subscription.

Increment 2 implementation includes local SMTP capture, profile and verified email
changes, session management, explicit admin bootstrap, PostgreSQL migration checks,
and account isolation/concurrency/browser tests. See [accounts](accounts.md).
Increment 3 now includes database-managed free plans, admin editing/defaults and
assignments, a user plan/usage page, migration backfill, atomic reservations,
idempotent terminal accounting and a separate processing-expense ledger. See
[plans and usage](plans-and-usage.md). Price mappings and paid activation stay with
Stripe checkout in increment 6; all currently assignable plans are free.
Increment 4 (durable user analysis) is next after review and acceptance. It must
connect quota reservation to job persistence before any dispatch, and implement
lease recovery and artifact retention.

### Later increments

Prioritize based on self-service user demand: two-region comparison, additional
variables/datasets, scheduled refreshes, reports/notebooks, teams, then a second
scientific domain. STAC is a candidate requiring processing as well as discovery.
Research Radar integration comes after independent product viability.

### Decisions needed at the relevant milestone

1. Before publishing plans: currency, prices, limits, retention, trial/demo policy,
   and the charging policy for failures and retries, informed by measured costs.
2. Before email-enabled onboarding: sender domain and delivery provider.
3. Before deployment: domain, host/database/storage choices based on benchmarks.
4. Before accepting money: business/billing identity, applicable customer policies,
   configured Stripe products/prices and live webhook acceptance.

No paid account setup is required for increments 1–2; email is captured locally.
