# Product decisions

Updated: 2026-10-13. Owner: Stepan Vasylevskyi.

## Accepted direction

Scientific Dataset Copilot is a **self-service subscription SaaS from its first
commercial release**, like Scientific Research Radar. This supersedes the earlier
services-first concept. Customers must be able to register, select a subscription,
pay, run supported analyses, export results, and manage their subscription without
manual onboarding or founder-operated analysis delivery.

The broad product supports multiple sciences through source connectors, domain
modules, and processing capabilities. The first supported workflow is a single
region's SST time series through a curated NOAA ERDDAP source. The ten-year Canary
Islands example anchors scientific acceptance; it is not the only eventual user input.

## First paid release

- Public product page and Subscription Plans page with clear supported capabilities.
- Self-service accounts, email verification, recovery, profile management, and sessions.
- Application-managed plan definitions and limits, with Stripe product/price mappings.
- Checkout, subscription management, and webhook-verified entitlements.
- Natural-language requests translated into editable, validated analysis proposals.
- Supported-region selection, date selection, source/method explanations, and bounded runs.
- Persisted owner-scoped analyses, progress, history, CSV/image export, and provenance.
- Visible usage limits and a defined treatment of failed, retried, and cancelled runs.
- Admin views for users, plans, source health, runs, operational errors, and costs.
- Tested deployment, backups/recovery, required customer-facing policies, and support route.

The first release serves individual accounts. Team invitations, organization roles,
shared billing, and collaboration are later capabilities; the persistence design
must allow a personal workspace to become an organization workspace without moving
scientific records between unrelated owners.

## Commercial assumptions to validate

Initial audiences: environmental consultants, marine NGOs, science communicators,
educators, and technical users exploring open data. The differentiator is a verified
data workflow with transparent provenance, not a general scientific chatbot.

Exact tier names, prices, currency, allowances, retention, and free trial/demo policy
are undecided. Earlier suggested prices are hypotheses, not implemented defaults.
Measure download, CPU/memory, storage, AI, and support costs before deciding allowances.
Do not promise unlimited analysis or enable paid features solely because a checkout
redirect reports success.

## Working agreement

- The agent may implement, test, push branches, and open PRs by default. Stepan merges.
- Use small, complete increments; no fixed launch date.
- Prefer economical infrastructure while preserving necessary performance and reliability.
- Evaluate paid commitments case by case; no pre-agreed spending ceiling.
- Routine engineering decisions are autonomous. Material scope, cost, and commercial
  decisions receive a concrete recommendation for review.
- Reuse suitable Radar and Margin Protection patterns after inspecting current code.
  This is a separate product with separate secrets, customer data, and billing configuration.
