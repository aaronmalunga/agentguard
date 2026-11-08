# Decision log

Every significant decision, pivot and correction, newest first. Real architectural decisions also get an
[ADR](adr/). Format: **date — decision** · why · what changed.

## 8 Nov 2026 — Core guard + held-out look #1

- **Requirements review:** the official guide says AI "must do meaningful work in the experience or functionality",
  so the AI layer is the next build item (Devpost early check flagged it). Hub: `FOOLPROOF_REVIEW.md`.
- **Guard core built:** rules engine, local hidden-instruction detector, monotonic levels approve < hold < ask_first
  < block (D1), counterfactual reasons (N4), approval facts kept apart from agent text (OWASP ASI09). 99 tests.
- **Held-out look #1** (rules-only and rules + detector): see evaluation-plan s.8, including why the 100% overstates
  generalisation. Detector frozen at `5e48324`; v2 independent-wording attacks pre-registered.

## 7 Nov 2026 — Light day

- **Mandate model** (`agentguard.mandate`): immutable, versioned (`revise()`, `revoke()`), money in cents, inclusive
  limits, timezone-aware dates, SHA-256 fingerprint of canonical JSON (64 chars, fits PayPal `custom_id`, decision D2).
  All 380 catalogue mandates parse without changing meaning (tested).
- **AWS moved after submission** → [ADR-0008 amendment](adr/0008-aws-services-in-sprint.md). Receipts use a local
  Ed25519 key in the sprint.
- **Competitor scan:** several entries already ship hold-then-capture/void and signed-intent ideas, so our edge is
  measured evaluation; we make no "first/only" claims on shared ideas.

## 6 Nov 2026 — Light day (token budget)

- Closed review findings **A4** (money in integer cents), **B2** (card-number helper out of product code, enforced by a
  test), **B4** (USD-only allowlist). 56 tests pass, 95% line coverage.
- Community files: CONTRIBUTING, issue templates (including "attack that got through", the front door for outside
  red-teaming), PR template.
- **Schedule re-ordered:** heavy build moves to Sun 8 Nov (afternoon) → Wed 11 Nov; Fri/Sat stay light. See STATE.md.

## 5 Nov 2026 — Sprint day 1

- **Attack catalogue v0 frozen before any guard rule exists** → [evaluation plan](evaluation-plan.md). 260 synthetic
  cases (210 attacks, 50 benign), 12 families; held-out split **by template** (90 cases, 34.6%) so held-out attacks use
  techniques the rules were never tuned on; SHA-256 enforced by a test and by CI. Metrics, pass marks, baselines and
  the keep-a-layer rule pre-registered in the same commit. A label audit refuses to build if a label breaks the policy.
  *Changed:* the delivery-address hard limit compares street/city/postcode/country; a recipient-name change alone is
  "ask" (found by the audit).
- **Storage: PostgreSQL, budget reserved by one conditional UPDATE** → [ADR-0007](adr/0007-storage-postgres-atomic-reservation.md).
- **AWS services pulled into the sprint** (Budgets first, IAM, Parameter Store, KMS, S3 Object Lock, Bedrock) →
  [ADR-0008](adr/0008-aws-services-in-sprint.md). Revises ADR-0002's 30 Oct gate.
- **PayPal client on the APIMatic-generated `paypal-server-sdk`, built with the PayPal Server SDK Context Plugin.**
  Rules taken from the plugin's skills: (1) pass the sandbox environment explicitly and check the resolved URL
  (`Environment.PRODUCTION == 0`); (2) build the client once and reuse it (token caching); (3) catch
  `AuthValidationException` separately (not an `ApiException`); (4) POSTs are never auto-retried, so retries reuse the
  same `PayPal-Request-Id`; (5) stub the OAuth token endpoint separately in tests. Found by our own tests: optional
  fields must be omitted with `APIHelper.SKIP`, not `None` (which sends `null`); network errors must become
  "outcome unknown, retry with the same request id". Friction log: [paypal-feedback.md](paypal-feedback.md).
- **FakePayPal** (transport-level, stateful) copies the proven sandbox behaviours, for tests, keyless CI and demo mode.
  It is not PayPal; no latency number is ever taken from it.
- **Adversarial review of day 1** → [review-2026-11-05.md](review-2026-11-05.md). Main finding: every v0 block case
  also broke a hard limit, so rules alone would score ≥ 84% by construction. *Changed:* froze supplement catalogue
  **v1** (120 cases, all inside the limits; 35 held out) and an "AI-dependent subset" pass mark, still before any rule
  exists. 13 more gaps logged with owners and days; 6 decisions left open for Aaron (D1–D6).
- **Decisions D1–D4 approved by Aaron (15:24):** two kinds of "ask" (ask-first for manipulation, hold for price/item
  doubt); buyer approves the mandate through PayPal and the receipt hash goes in the order's `custom_id` (after a
  sandbox round-trip check); cart and prices from the merchant's system, never the agent; page text from the MCP proxy,
  never the agent. Adversarial review becomes a daily step → [review-process.md](review-process.md).
- **Live smoke test can't run from Claude's sandboxed shells** (PayPal hosts aren't on their network allowlist); Aaron
  runs `scripts/smoke_gateway.py` on his laptop.

## 14 Oct 2026 — Project start (Stage 0)

- **Agent framework: Strands Agents for the demo agent; guard framework-free** → [ADR-0005](adr/0005-agent-framework-strands.md).
  *Why:* trust boundary (agent asks, guard moves money); MCP built in; Apache-2.0; Bedrock-ready.
- **Two decision points instead of one** → [ADR-0001](adr/0001-two-decision-points.md).
  Clear violations are blocked *before* authorization; only uncertain cases are authorized and held for a human.
  *Why:* PayPal's data ([S5](sources.md#s5)) shows the benefit of fraud prevention comes from stopping it upstream; an
  authorization already reaches the issuer and holds buyer funds. *Changed:* the brief's single "authorize → guard →
  capture/void" flow.
- **Dropped the original pitch hook.** The quote "PayPal does not assess AI intent or behavior" could not be found at
  its cited source. *Replaced by* PayPal's own merchant research ([S1](sources.md#s1)): liability for disputed agent
  purchases is "in flux". *Why:* every pitch claim must be verifiable.
- **Wording correction:** PayPal's AP2 post says mandates *could* feed fraud models and dispute evidence — stated as
  possibility, not a deployed feature ([S2](sources.md#s2)).
- **Unit 42 corrections:** "fake merchants" is not a separate scenario in the article; line-item display and
  shipping-scan checks are our inference ([S3](sources.md#s3)).
- **Direction-agnostic guard** → [ADR-0003](adr/0003-direction-agnostic-money-movement.md). One pipeline for any agent
  money movement: buyer purchases first (core), merchant refunds next (stretch).
- **Deployment: Render + AWS** → [ADR-0002](adr/0002-deployment-render-and-aws.md). Render hosts the always-on judge
  demo; AWS serverless is the architecture showcase, gated on the 30 Oct core-flow checkpoint.
- **Least-privilege sandbox app** → [ADR-0004](adr/0004-least-privilege-paypal-app.md). Only the PayPal features we use
  are enabled; Payouts is off.
- **Stage 0 spike passed** ([evidence](../spike/)): authorize/capture/void, idempotent capture, Vault charge with no
  cardholder present, and a decline that returns HTTP 201 with authorization `DENIED` → the guard must check payment
  status, never only the HTTP code.
- **CI blocked by GitHub account billing lock** (job never started; not a code failure). Until resolved, CI steps are
  replayed locally before each push. Workflow runner pinned to `ubuntu-24.04` for reproducibility.
- **Spike bug fixed:** a logging parameter named `status` collided with the payment `status` field. Lesson: name values
  by meaning (`http_status` vs payment status); covered by unit tests from Phase 1.

## Before 14 Oct (from planning)
- Name **"AgentGuard — built on PayPal"** (never "PayPal AgentGuard"), licence **Apache-2.0**, **sandbox only**,
  fresh repository with no reused course code.

- 2026-10-14 · ADR-0006: LLM provider-agnostic; model chosen by pre-registered bake-off (Gemini / OpenAI / Anthropic, direct accounts); Bedrock on AWS deploy.
- 2026-10-14 · Spike v2: approvals expire before 3-day honour period → auto-void (D2); refund guard adds only what PayPal doesn't enforce (D3); agent never uses toolkit create_order, which hard-codes CAPTURE (D4); catch before capture: void = $0 fee, refund = fee lost (D5).