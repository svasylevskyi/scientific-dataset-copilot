# Plans and usage

Increment 3 adds database-managed free plans, workspace assignments and transactional
analysis allowances. Stripe products, prices, payment activation and checkout are
deferred to the billing increment. There are no paid entitlements or API keys to
configure in this release.

## Testing the feature

Deploy with the normal development script. Migration `0002_plans` creates the
Development plan and assigns every existing workspace to it. New registrations
receive the configured default in the same transaction as their account/workspace.
Repeating a deployment does not reset plans or usage.

The initial plan is free: 20 analyses per calendar month, one simultaneous analysis,
up to 3,663 days per analysis, and 30 days of result retention. These are editable
testing allowances, not published commercial pricing. The scientific connector's
independent safety limits still apply.

1. Sign in and open **Plan and usage**. Confirm the plan, allowance, UTC reset date
   and empty usage history. The existing reference and query planner are free.
2. Sign in as an administrator and open **Manage plans**. If necessary, promote your
   already registered/verified account using the documented admin CLI.
3. Create a second plan, edit its limits, and make it the registration default.
   Register a new account through Mailpit; it receives the new default. Existing
   accounts keep their assignments.
4. Assign a plan to an existing account using its email. Suspend and reactivate its
   analysis access. Suspension leaves sign-in and already accepted work intact.
5. Archive a non-default plan. It disappears from assignment choices while existing
   members retain access. Activate it to accept new assignments again.

There is no live execution button yet. Usage remains zero until the worker increment
calls the internal admission service. The UI states this explicitly. Retention
values are recorded for future runs; no artifact-deletion worker is introduced here.

## Plan policy

- Only administrators can create/edit/archive plans, change the default or assign
  account plans. Writes require the same Origin/header CSRF checks as account writes.
- One singleton row selects the registration default. It cannot be archived until
  another active plan is selected. Catalogue writes serialize against registrations.
- Existing assignments do not change when the default changes. Archiving prevents
  new assignments; it does not suspend existing members.
- Limits apply immediately to new reservations. Reducing an allowance below existing
  usage shows zero remaining and blocks new runs; it does not cancel accepted runs.
- Reassignment and suspension preserve all workspace usage. Accepted runs can still
  settle. Retention is snapshotted per reservation and is not shortened by plan edits.
- Edits carry a plan version; a stale editor receives a conflict and must refresh.
  Plans are archived rather than deleted so historical reservations remain valid.

## Quota and worker contract

The allowance unit is **one analysis run**. Each personal workspace has one allowance;
admins have the same limits as other members when submitting their own analyses.
Periods are calendar months, starting at 00:00 UTC, with no rollover. Read APIs
show completed, reserved and remaining units, concurrent reservations across all
months, and the latest 20 reservation records.

`app.plans.service` exposes internal transactional operations, with no public HTTP
endpoint for clients to mint, consume or release their own allowances:

1. Authorize workspace ownership and validate the query/connector safety limits.
2. Call `reserve` with an immutable run UUID, the normalized request's SHA-256 and
   its inclusive date span. It locks the workspace assignment, reads the current
   plan under a shared lock, and checks active access, monthly allowance, concurrent
   slots and date span. One `reserved` event is appended.
3. In the **same database transaction**, persist the immutable run and durable job
   or outbox. Commit before dispatch. If persistence fails, rollback also removes
   the reservation and event. This integration is required in increment 4.
4. The worker calls `settle` once the run has a confirmed terminal outcome:
   successful → consumed; failed/cancelled → released. Append the terminal event
   in the same transaction as the terminal job state and result publication.

Duplicate admission returns the existing reservation state. Different inputs under
the same run key are rejected; the worker must not redispatch terminal reservations.
Duplicate terminal events with the same outcome are idempotent. Conflicting final
outcomes return a conflict rather than refunding or charging twice. Automatic
processing retries keep the same reservation; a deliberate new run gets a new key.

Runs finishing next month settle against their original period. Outstanding
reservations from older months still occupy a concurrent slot. Reservations are
**not automatically released on a timer**, since a disconnected worker may still
be executing. The worker increment must reconcile abandoned runs using leases and
confirmed terminal state before releasing their reservations.

The assignment lock is shared by reserve/settle/reassignment. Plan read locks
serialize limit edits with admission while allowing different workspaces to reserve
concurrently. Services borrow the caller's transaction and do not commit or perform
network requests. Keep one workspace's accounting in each transaction.

## Expense accounting

`record_cost` stores nonnegative USD expenses with six decimal places and an
idempotency key per reservation. Provider/compute expense is separate from customer
allowance: failures may release a quota unit while retaining their actual expense.
Conflicting retries of the same cost event are rejected. This is an accounting
foundation, not a price estimate or a customer charge; no provider calls are added.

## Verification

PostgreSQL tests cover migration/backfill and repeat upgrade, default assignment,
role/owner isolation and CSRF, stale edits, archiving, reassignment, suspension,
concurrent admission against monthly/concurrency limits, duplicate terminal events,
rollback, cost idempotency, and UTC year/month rollover. CI runs the real admin/member
journey at desktop/mobile sizes and checks plan assignment through the HTTPS gateway.

The database remains authoritative; UI counters are informational. The next worker
increment must connect admission, job persistence, lease recovery, cost reporting
and artifact retention before enabling live runs.
