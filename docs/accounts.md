# Accounts and persistence (increment 2)

## Boundaries and data

PostgreSQL is the only supported account database. SQLAlchemy owns mapping and
transactions; Alembic owns schema changes. No automatic `create_all` or SQLite
fallback runs at startup. The API's `/api/v1/health` endpoint is a database-free
liveness check; `/api/v1/ready` checks the migrated account table.

A user owns one personal workspace. Workspace IDs are the future ownership root
for saved analyses; this increment does not persist scientific runs. Every
workspace lookup filters by the authenticated owner, including administrator
requests. Private missing/foreign IDs both return 404. Roles are constrained to
`user` and `admin`; public registration/profile inputs cannot set roles.

Account changes commit before the response is sent. User-row locks serialize
credential changes, session rotation and email-token consumption; concurrent
requests cannot consume the same token twice or issue a session with credentials
invalidated by a concurrent password reset. Unique normalized emails and unique
workspace ownership are enforced in PostgreSQL.

## Passwords and sessions

- Passwords use Argon2id, with independently salted hashes, 64 MiB memory, three
  iterations and parallelism four. Passwords accept 12–128 characters, including
  spaces and Unicode. The app does not impose arbitrary character-class rules.
- Browser sessions use an opaque UUID plus a cryptographically random secret.
  Only SHA-256 token digests are stored. Tokens are never returned in JSON or
  written to local storage. The cookie is HttpOnly, SameSite=Lax, scoped to
  `/api/v1`, and Secure for non-local deployment.
- Sessions expire after seven days without renewal, with a hard 30-day maximum.
  The signed-in browser rotates its session every 15 minutes. Rotation replaces
  the token atomically. A known previous token returns 409 during a 30-second
  concurrent-tab grace period; no cookie is cleared or reissued. Reusing that
  previous token later revokes the session. Other invalid secrets grant no access.
- Logout and per-device/all-device revocation are database-authoritative and
  immediate. Password reset/change and confirmed email changes revoke all sessions
  and pending email tokens. Account deactivation is checked on every request.
- Sensitive writes require the configured exact Origin, an application request
  header and JSON content type. There is no permissive CORS configuration. Account
  responses use `Cache-Control: no-store` and no-referrer headers.

## Email and recovery

Verification links expire after 24 hours; recovery and email-change links expire
after 30 minutes. They are random, hashed in the database, purpose-bound and
single-use. A replacement link invalidates its predecessor. A GET never consumes
a link: the user must confirm in the app. The token is in the URL fragment, which
is not sent in HTTP requests or Referer headers, and is removed after success.

Registration and recovery return generic eligibility responses. Duplicate
registration never overwrites an existing password or profile. Unverified users
cannot sign in. Email changes require the current password and confirmation of
the new mailbox; the old address stays active until confirmation succeeds.

SMTP delivery is synchronous with a ten-second connection timeout. Delivery
failure returns a retryable error and rolls back the operation. If delivery
succeeds but the database commit fails, the link is unusable; requesting a new
link recovers. A durable mail outbox is a future reliability improvement before
public launch. Passwords and token values must not be included in application logs.

Mailpit is the local inbox only and cannot be used for public delivery. Production
SMTP is configurable through `SDC_SMTP_HOST`, `SDC_SMTP_PORT`, `SDC_MAIL_FROM`,
`SDC_SMTP_USERNAME`, `SDC_SMTP_PASSWORD`, and `SDC_SMTP_STARTTLS`. A sender domain and
provider still need selection before public onboarding. Put credentials in the
deployment secret store; `.env` is ignored by Git.

## Abuse limits and administration

PostgreSQL-backed rate buckets are shared across API processes and committed even
when an authentication attempt fails. Defaults: 60 sensitive attempts per client
IP per five minutes, ten login attempts per address per 15 minutes, and one email
of each purpose per address per minute (registration and verification resend share
a bucket). Responses return 429 and `Retry-After`. Unknown addresses receive the
same limits. Configure a trusted proxy before deployment; do not accept arbitrary
forwarding headers as client identity.

`python -m app.accounts.cli promote EMAIL` explicitly grants admin to an active,
verified account; `demote` removes it. The initial admin page exposes aggregate
account/workspace counts only. Role changes take effect on the next request.
`python -m app.accounts.cli cleanup` removes expired rate buckets and authentication
records expired for more than seven days. Schedule cleanup in a production runbook.

Before public deployment: HTTPS and Secure cookies, trusted proxy configuration,
production SMTP, database backups, migrations as a separate release step, cleanup,
public policy/support pages and the roadmap's remaining launch gates are required.
`SDC_PUBLIC_URL` must be an origin without a path, and non-local origins are rejected
unless HTTPS and `SDC_SECURE_COOKIES=true` are configured. Compose is local-only.

## Validation

CI uses actual PostgreSQL for migration upgrade/downgrade/drift checks and for
account persistence, ownership, admin restrictions, rate limits, session lifecycle,
concurrent refresh/reset, single-use links and email failure tests. A separate
browser journey uses real SMTP delivery to Mailpit on desktop and mobile.
The Linux/Windows matrix verifies Python 3.14.7, Node 26.6.0, scientific results,
request security, generated API types, builds and reference browser flows.

Implementation references: [SQLAlchemy PostgreSQL/psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg),
[OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
[OWASP sessions](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
[Mailpit Docker](https://mailpit.axllent.org/docs/install/docker/).
Radar's current session model/service were inspected on 2026-10-13. The design
reuses row-based revocation, bounded rotation and conflict handling, while using
opaque same-origin sessions suitable for this application's current needs.
