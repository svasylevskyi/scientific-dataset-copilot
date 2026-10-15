# Guided copilot planning

Verified members can describe an analysis in **Your analyses**, answer clarification
questions, review/edit a proposal, and explicitly save it. Saving does not start
scientific work. **Run analysis → Start run** remains the separate execution and
allowance confirmation. The existing manual form works without an AI key or during
a provider outage.

Supported scope: monthly regional sea surface temperature in °C from NOAA OISST v2.1,
for one preset (Canary Islands or Madeira) and a historical date range. Other
variables, sources, regions, comparisons, anomalies, forecasts and generated code
are not supported. Ambiguous dates or temperatures require clarification. This
increment does not generate interpretations of scientific results.

## Enable locally or on the development server

No configuration changes are required to deploy with planning disabled. Migration
`0004_copilot` runs through the existing deployment workflow and preserves accounts,
plans, analyses and artifacts.

Create a dedicated OpenAI project API key with permission to create Responses.
Keep it server-side. On the Hetzner server, edit the **existing**
`~/scientific-dataset-copilot/.env.development` and append:

```dotenv
SDC_COPILOT_ENABLED=true
SDC_OPENAI_API_KEY=YOUR_PROJECT_API_KEY
SDC_COPILOT_DAILY_REQUESTS=20
SDC_COPILOT_DAILY_BUDGET_USD=2.00
```

Preserve the existing domain and database password. Do not rerun `configure.py`.
After merging, use **Actions → Deploy development → Run workflow → main**.
The key is passed only to the API container, not to the frontend, worker, migrations
or GitHub Actions. The API needs outbound HTTPS to `api.openai.com`; no new inbound
ports are needed. Avoid printing resolved Compose configuration, which includes
container environment secrets. Setting `SDC_COPILOT_ENABLED=false` and redeploying
disables new paid planning calls without disabling the manual workflow.

For native local development put the same variables in the repository's `.env`
and restart the API. Local Docker Compose reads these variables from `.env` too.
Use a dedicated development key/project. Do not paste API keys into chat or commit
them. This integration uses the API account's billing, not a ChatGPT plan.

## Try it

1. Sign in, open **Your analyses**, and enter “Show sea surface temperature around
   Madeira.” Submit and answer the date question with “January 2020”.
2. Review source, method, units, bounding box, dates, coverage warnings, retention
   and the one-analysis allowance. Edit the title or dates and **Validate edits**.
3. **Confirm and save analysis**. Confirm that no run or allowance reservation exists yet.
4. Use **Run analysis → Start run**. Inspect the existing progress, chart and exports.
5. Try missing dates, “temperature” without specifying sea surface, another variable,
   an unsupported region, or a two-region comparison. No unsupported proposal should
   silently become a supported analysis.
6. Reload during planning or review: **Check request status** retrieves the same
   request. A repeated request ID does not make another provider call. New request
   starts a separate planning attempt; it is never an automatic paid retry.

Proposal coverage uses the checked-in metadata snapshot, with its inspection date
and coverage end displayed. It is not a fresh provider availability check. Dates
beyond that snapshot require a different date range; the existing manual form and
worker can check newer source coverage. The worker always validates fresh NOAA
metadata before downloading. The AI never generates source URLs or calculates SST.

## Limits and accounting

- Default: 20 requests per workspace per UTC day, six admission attempts per minute,
  and one in-flight planning request per workspace. Each clarification is a request;
  a conversation has at most three requests. Input is capped at 2,000 characters per
  turn and output at 600 tokens. Provider timeout is 15 seconds, response size 64 KB.
- A single OpenAI Responses call uses strict JSON schema, no tools, no redirects,
  no automatic retries, `store=false`, and the pinned model
  `gpt-5.4-mini-2026-03-17` with reasoning disabled. Model choice is code-reviewed.
- Default global admission budget: $2.00 per UTC day across all workspaces. It is
  a configurable development control, not a published subscription allowance.
  Requests/day accepts 1–100; budget accepts $0–100. Zero budget stops new calls.
- Admission reserves a conservative estimate under a PostgreSQL transaction lock
  **before** network I/O; simultaneous requests cannot spend the same remaining
  budget. No database/authentication lock spans the network request.
- Reported input, cached-input and output tokens determine an estimated USD cost,
  using the recorded model/pricing version. Prices verified 2026-10-14: $0.75,
  $0.075 and $4.50 per million tokens respectively. These are estimates, not invoices;
  review the tariff if provider pricing changes. Keep provider-side spending
  controls appropriate to the project as well.
- A timeout, interruption or missing usage retains its conservative reservation
  for that admission day. Unknown cost is never represented as a free request.
  Abandoned requests become failed when read or at the next admission after two
  minutes; they are not automatically retried. Late usage can settle the estimate
  without publishing a stale proposal. The next UTC day has a fresh budget.
- Planning never reserves or consumes scientific analysis quota. Model expense is
  recorded on the planning request, independently of the existing run expense ledger.
  Failed planning can incur provider cost even though no analysis is created.

**Manage plans → AI planning usage** shows today's request count, estimated cost,
budget used/reserved and unknown-usage count. The admin endpoint exposes aggregate
usage only; administrators cannot read other members' prompts or proposals.

## Privacy and failure behavior

Only the user's bounded request/clarification transcript and the registered planning
instructions go to OpenAI. Account details, passwords, result files and arbitrary
external metadata are not included. The UI discloses this before submission.
Provider responses and errors are not logged or displayed verbatim. Model text is
parsed into enums/dates; application code produces all proposal details/questions.

Private transcripts, proposals, acceptance links and cost records persist in
PostgreSQL under workspace ownership; this increment has no automatic transcript
retention cleanup. Only the latest request ID is stored in the browser. `store=false`
does not change the API project's other provider retention policies. User-account
deletion and configurable prompt retention remain launch-readiness work.

Ready proposals are validated again when edited/saved. Saving is idempotent and
checks ownership, access, current plan date limits, source bounds and the existing
100-analysis limit. It does not imply that an analysis slot is available later;
the normal run-admission transaction rechecks all entitlements. Refused, malformed,
truncated or unavailable model responses never produce a runnable proposal.

## Verification and live model evaluation

CI uses deterministic provider fixtures: real PostgreSQL tests cover ownership,
idempotency, clarification bounds, quota separation, concurrent budget admission,
unknown-cost handling and independent provider I/O. Desktop/mobile browser tests
exercise clarification, reload, editing, explicit save/run, results and manual
fallback. No CI job needs a paid API key or contacts OpenAI.

These fixtures verify application behavior, not the model's semantic accuracy.
Run the shipped 15-case live evaluation after configuring the key:

```bash
bash deploy/development/compose.sh exec api python -m app.copilot.evaluate
bash deploy/development/compose.sh exec api python -m app.copilot.evaluate --live
```

The first command makes no provider calls. The second explicitly makes paid calls,
with a separate fixed $0.50 maximum conservative reservation for the whole corpus,
no retries, and pass/fail output per case. It runs outside member usage accounting.
Relative-date cases use a fixed 2026-10-14 reference date for reproducibility.
Cases include missing/ambiguous fields, unsupported science/regions/comparisons,
clarifications, external URLs and instruction injection. Require all cases to pass
and complete the browser smoke test before considering guided planning accepted.

Sources: [model, snapshot and pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini),
[structured output contract](https://developers.openai.com/api/docs/guides/structured-outputs).
