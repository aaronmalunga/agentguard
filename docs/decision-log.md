# Decision log

Every significant decision, pivot and correction, newest first. Real architectural decisions also get an
[ADR](adr/). Format: **date — decision** · why · what changed.

## 10 Nov 2026 — Dependency regression caught: the agent library downgraded the guard's Gemini client

- **What happened:** adding `strands-agents[gemini]` as a project extra (`ef7e83e`) made uv resolve one version for
  the whole lock: `google-genai` 3.0.0 → **2.34.0**. Render installs from the lock, so the **live guard ran on
  2.34.0 from about 11:50 to this fix**. Same model; but a live AI check took 6.2 s against the usual 1–1.5 s,
  consistent with the older client not applying our minimal-thinking setting (inference, not verified).
  All published results (v2, v3, held-out) were measured on 3.0.0.
- **Caught by:** Aaron noticing `- google-genai==3.0.0` while the agent experiment was installing; lock diff confirmed.
- **Fix:** `uv.lock` restored to the last measured state + MCP only (diff: 0 changed, 0 removed, 11 added, all
  MCP's own dependencies). Strands now runs in its own environment (`uv run --isolated … --with
  "strands-agents[gemini]"`), so the agent's needs can never change the guard again. Agent experiment restarted
  after the fix; the first, aborted lines (guard on 2.34.0) are kept and labelled, never mixed into results.
- **Lesson / fundamental:** one lock file = one dependency graph; an optional extra can still change the core's
  versions. Check `uv.lock` diffs for the core's packages on every dependency change (added to review checklist).

## 10 Nov 2026 — Pressure test of the MCP adapter against PayPal's toolkit (before any agent run)

- Checked against `github.com/paypal/agent-toolkit` (commit `a3aa963`, 1 Sep 2026): its order tools are
  `create_order`, `pay_order`, `get_order_details`. Ours were `create_order`, `get_order` → renamed
  `get_order_details`. No `pay_order` on purpose (capture only after AgentGuard's checks or the buyer's approval).
  Claim wording fixed: **same order-tool names, stricter arguments, not a drop-in replacement.**
- `items` was an untyped object list; strict function calling (Gemini) can reject objects without declared
  fields → now a typed `OrderItem {sku, quantity}`; a test pins the schema. Strands sends it via Gemini's
  `parameters_json_schema`. Plan and outcome rules unchanged (PLAN.md hash unchanged; no run had happened).

## 10 Nov 2026 — MCP adapter + Strands agent with a repair loop (step 6; Meta-winners "agent loop" test)

- **MCP server** `agentguard-mcp` (mcp 2.3, MIT): 4 tools shaped like PayPal's agent toolkit (`list_products`,
  `read_shop_page`, `create_order`, `get_order`); no approve/capture/refund tool; the agent key stays in the server's
  environment (no token passthrough); idempotency key derived from (mandate, items, page, stated total), so a
  repeated request is one payment and a repaired one is checked afresh. New agent-only endpoints:
  `GET /api/agent/mandate` (buyer's words + version, not the limits) and `GET /api/agent/payments/{id}` (own payments
  only, 4 finding fields). Optional extra `agent` (mcp, strands-agents[gemini], Apache-2.0); CI installs all extras.
- **Pre-registered before any run:** `eval/agent_runs/PLAN.md`, SHA-256
  `24edb9433897c5a191bb75e2713e636135bbf595f218f67e3520f7d964d132ba`. 4 groups × 10 (normal, poisoned single shot,
  agent lies, repair after block); outcomes classified by code; target harm 0/40. Runner `scripts/agent_runs.py`
  (`agent_runs.bat`); the agent model must differ from the guard's. One clarification to the runner before any run:
  a run with zero orders counts as `stopped`, not `not_fooled` (as the plan already says).
- Checked here without a model key: Strands launches the MCP server as a subprocess against a live local
  AgentGuard; a poisoned order is held before PayPal and shows in the buyer's console as a verified agent. Tests
  199 → 205. Threat model: E2 covered; new M10 (refusal reasons as an oracle) partial.

## 10 Nov 2026 — Per-agent keys (review M1)

- **Options:** keep one shared agent token (agent ID is self-reported) · signed requests per agent (keypair, more
  work for every client) · **revocable per-agent bearer keys (chosen)**: works with any MCP client today.
- Buyer mints a key in "Your rules → Connect an agent" (`POST /api/agent-keys`); shown once, only its SHA-256 kept,
  max 5 per session; revoke → 401 `agent_key_revoked`. A key acts inside its buyer's demo session, so an agent on a
  laptop (no cookie) lands in that buyer's console. The payment records the key's agent ID and ignores the one in
  the body; `agt_` IDs are reserved, so "verified" can't be claimed with the shared token. Mint/revoke are logged
  in the hash chain. Session switch happens in middleware, because FastAPI runs sync auth checks in another thread
  and a context change there would not reach the endpoint.
- Tests 196 → 199; headless Chrome: mint in browser → pay with key from a cookie-less client → recorded as
  `agt_…`, verified; 0 console errors. Fundamental: authentication tells you *who*; never take identity from the
  payload.

## 10 Nov 2026 — Terms audit (rules, Gemini, Channel3) → sources S7–S9

- Read in full: Devpost Official Rules, Gemini API Additional Terms (23 Mar 2026), Channel3 Publisher Terms (2 Nov
  2026). Findings and what we do about each: `docs/sources.md` S7–S9.
- **Channel3:** per-call Channel3 timings removed from the API response, the decision log and three committed
  smoke files (marked `_redacted`), because their terms forbid publishing benchmarks of the service without
  consent. Reuse notice added to README and the shop page. Our own step times in the decision trace stay.
- **Gemini:** free tier may not serve EU/UK/Swiss users. Options: paid project ($5 prepay, Aaron checking), or
  recorded answers only on the hosted demo. Decision pending; until then nothing changes on the live site.

## 9 Nov 2026 (late) — Webhooks drive payment state (review W4/W5) → ADR-0009

- **Forward-only state machine** (`flow/paypal_events.py`): verified PayPal events now move status (held/unknown →
  captured, voided, declined; captured → partly refunded → refunded, or reversed) and the budget follows. A late or
  repeated event never moves status back; it is logged "unchanged". Console: "Refunded outside AgentGuard",
  "Reversed (chargeback)", "Disputed".
- **Transactional inbox:** event ID (primary key), status, budget and audit entry in one SQLite transaction; the
  in-memory `SeenEvents` is gone. A crash mid-way rolls back so PayPal's retry is processed.
- **Disputes:** `CUSTOMER.DISPUTE.CREATED` matched via `disputed_transactions[].seller_transaction_id` (= capture ID,
  PayPal docs) → flag + evidence (mandate fingerprint, receipt SHA-256, key ID); not sent to PayPal (T11, roadmap).
- Proof so far: tests with PayPal's documented event shapes (not captured events); 181 → 196 tests. **Live proof
  pending:** Aaron refunds one captured sandbox payment from the business account; dispute event box to tick in the
  webhook settings.
- **Devpost rule (email, 9 Nov 22:27):** after the deadline nothing changes — no commits, README edits or video swaps
  until winners are announced. So the live demo at 12 Nov 22:00 SA is what judges use until 15 Dec.

## 9 Nov 2026 (late) — Threat model (review J3)

- **`docs/threat-model.md`:** STRIDE per trust boundary (agent, page, AI, PayPal, browser), money-path risks, OWASP Top
  10 for LLM Applications 2025 (LLM01 injection and LLM06 excessive agency measured), each risk → control → test or
  live run → status. Open items ranked: approval fatigue (20% held-out step-ups), per-agent keys (step 4), webhook
  state machine (step 3), whole-chain rewrite, honour-period auto-void, mandate re-check at approval, dependency scan.
- **Found while writing it and fixed (E3):** no browser security headers, so the approval page could be framed by
  another site (clickjacking an Approve click). Now every response sends `frame-ancestors 'none'` + `X-Frame-Options:
  DENY`, `nosniff`, `Referrer-Policy: no-referrer`, HSTS; the app page gets a strict CSP (scripts from this origin
  plus the one inline theme script by SHA-256 hash, no `unsafe-eval`); `/docs` keeps Swagger's CDN. Checked in headless
  Chrome against the real page: first run caught AG Grid's `data:` icon font being blocked → `font-src 'self' data:`;
  second run zero CSP errors. Test `test_security_headers_on_app_and_api`; tests 180 → 181.

## 9 Nov 2026 (late) — Docs honesty (review J2)

- **ADR-0006 amended:** the LLM bake-off was not run (no paid keys); `gemini-3.5-flash-lite` was chosen by constraint
  (free route + D14), then tested on v2, v3 and held-out. Tool-call accuracy never measured. Small bake-off only if
  keys arrive by Wed and it is pre-registered first.
- **ADR-0005 amended:** the demo agent has been scripted; Strands arrives with the MCP adapter, or is labelled roadmap.
- **Evaluation plan s.8 / AI governance s.6:** anomaly model (config 4) and LLM-as-judge marked "designed, not built"
  with reasons; consistency and cost-per-1,000 marked not run; stale gaps (audit log, D3, D4) closed. README limitation
  line added. No result changed.

## 9 Nov 2026

- **UI polish from Aaron's review (17:20):** AG Grid icons were empty squares because we shipped the "no-font" Quartz
  theme → full theme (same version 32.3.3, MIT); grid rows 52 px with centred status and action cells (pills were
  clipped); product photos on a warm tile, multiplied in so the white photo background disappears; plain-language
  copy (no dates or "red team" in the shop panel; "reserved, not taken" instead of "authorised"/"voided"); nicer rule
  labels; wider approval card.
- **PayPal webhooks (Aaron: "give the judges what they ask for", 17:30).** `POST /api/webhooks/paypal`. An event is
  believed only after PayPal's verify-webhook-signature postback says SUCCESS; cheap checks first (5 headers present,
  certificate URL on paypal.com) so junk never costs a PayPal call; de-duplicated by event ID (PayPal retries for up
  to 3 days); a verified event is appended to that payment's hash-chained audit log. Off unless `PAYPAL_WEBHOOK_ID`
  is set. Options: postback (chosen: documented, no crypto code to get wrong) vs verifying the RSA signature
  ourselves (faster, no extra call, more to get wrong). Simulator events can't be verified (PayPal docs), so the live
  test needs real sandbox events. Tests 167 → 179.
- **Judge pressure test of the live site (16:00–16:20 SA), fetch calls from the public page.** Held: 8 bad mandates
  refused with 422 (zero/negative budget, item price above budget, EUR/unknown currency, expired or inverted dates,
  empty categories); same mandate twice → 409; agent token can't approve, reject or set rules (403); buyer token can't
  submit payments (403); bad or missing token → 401. **Live AI on a page it had never seen** (hidden gift-card
  instruction): detector and `gemini-3.5-flash-lite` (1,648 ms, live, not recorded) both flagged it → ask first,
  PayPal never called. **Two gaps found and fixed:** (1) no per-IP limit on the calls that spend PayPal sandbox or the
  shared Gemini free quota → 30 a minute per IP on run/pages/draft/payments/approve/reject, 429 + Retry-After; reads
  never limited; IP = Cloudflare's `True-Client-IP` (first try keyed on X-Forwarded-For, which on Render is the proxy and changes per request: live check, 32 calls, no 429). (2) a $10 trillion budget was
  accepted → mandates capped at $10,000 (larger spending needs a different approval path, roadmap). Tests 165 → 167.
- **D14 done:** all 5 scripted demo scenarios now replay real recorded answers from `gemini-3.5-flash-lite` (recorded
  9 Nov; 1,542 / 1,407 / 870 / 891 / 1,221 ms). The poisoned page was **blocked by the real model**. Free daily quota
  resets at midnight US Pacific (10:00 SA in winter, not 09:00 as first assumed); recording now paces calls 8 s apart.
- **Live check through the web app (Aaron, 11:02): 8/8 as expected** against the real PayPal sandbox: normal →
  captured (order `3G536656BB068221X`), poisoned → blocked (PayPal never called), inflated → held → buyer rejects →
  voided (`3L326523V8849980F`), out-of-stock swap → held (`15W78274PM189173V`), agent lies → asked first (PayPal never
  called), receipt verifies (3/3 checks), audit chain verifies (7 entries). AI answers in this run were the recorded
  real answers (D14), not new calls. `spike/results/2026-11-09_1102_api_smoke.json`.
- **Render Blueprint** (`render.yaml`): free plan, health check `/healthz`, secrets entered in the dashboard only.
- **Channel3 integrated (sponsor, Aaron 11:22):** the demo shop sells real Channel3 products; every decision looks up
  the live market price (free endpoint, 2.5 s limit, 15 min cache) as a soft signal that can only raise a hold. Review
  of the first snapshot: most products had 1 shop, so the picker now prefers well-known products sold by 3+ shops, and
  fewer than 3 shops is labelled "N shops only" on screen. Recorded AI answers are tied to the exact prompt, so any
  catalogue change means re-recording (5 calls); `refresh_demo.bat` does catalogue, recording and live check in order.
- **Demo budget $300 → $500 (11:45):** with real Channel3 prices the five scenarios cost more than $300 together, so
  the live check's last scenario was blocked as over budget (correct behaviour, wrong demo). Recorded answers are
  re-recorded because the buyer's wording is part of the AI prompt. Live check before the change: 7/8, with the 8th the
  budget rule working (`spike/results/2026-11-09_1135_api_smoke.json`); Channel3 market prices live on 5/5 decisions,
  3–6 shops each (per-call timings removed 10 Nov: Channel3 terms forbid publishing benchmarks of their service).
- **Per-visitor demo sessions** (review U6): each judge's browser gets its own budget, payments and log, so judges
  never spend or see each other's demo.

## 8 Nov 2026 (evening) — Web API, live-flow safeguards, v3 result

- **D13 (Aaron, 16:05): front-end style C** (product-grade: decision trace with model + latency, phone-style
  "Is this what you meant?" card), **with both light and dark mode** (one set of colour tokens; follows the device,
  plus a toggle). Additions accepted for later (16:11): a reactive "currency rain" driven by real decisions only
  (approve/hold/block; off on approval and console screens; off under reduce-motion), and the Impeccable detector
  (`npx impeccable detect`, 62 deterministic rules) as a design audit with before/after counts. Not adopted: the rest
  of the Impeccable skill pack and its live mode (runs an agent CLI with sandboxing off).
- **Web API (FastAPI)** over the existing engine: 20 endpoints, OpenAPI at `/docs`. Separate agent and buyer roles
  (agent can only ask to pay; ASI02/ASI03). One error shape. `Idempotency-Key` required on payments.
- **D3 enforced in the live flow:** the agent sends SKU + quantity only; titles, categories, prices and the payee
  account come from the merchant catalogue and registry. An agent-stated price or title that differs ⇒ ask first.
  Unknown or out-of-stock products ⇒ block, PayPal never called. **D4:** page text is referenced by `page_id` from
  AgentGuard's own capture; the agent can't send page text.
- **Hash-chained decision log** (`flow/audit.py`): every state change appends one SHA-256-linked entry in the same
  transaction as the head read; `/api/audit/verify` finds the first altered entry. Limit disclosed (whole-chain
  rewrite) → head copied into receipts; S3 Object Lock anchoring after submission.
- **Signed receipts of intent** (Ed25519, `flow/receipts.py`): exact mandate + fingerprint (= PayPal `custom_id`),
  catalogue facts, decision and reasons, AI model + latency, PayPal ids, chain head. Verifiable offline with only
  the public key (`scripts/verify_receipt.py`). Local key now; KMS after submission (ADR-0008 amendment).
- **Review fix:** pages longer than the AI's 4,000-character window ⇒ ask first (padding attack). Added in the flow
  layer, not the frozen engine. Full review: [review-2026-11-08-api.md](review-2026-11-08-api.md).
- **v3 result:** all 5 pre-registered v3 expectations met (rules 0/75 → + AI 71/75, 0 severe, 0/42 false blocks). The
  regression look #3 is reported as a **fail-safe** measurement, not an AI one (all AI calls hit the Gemini free
  quota, 429). See evaluation-plan s.8.
- **Web app screens built** (style C/A2, Wide steel type, light and dark): Shop and agent (scenarios, paste-your-own
  page, decision trace with per-layer timings, buyer phone card), Approvals, Console (AG Grid: filters, search, approve /
  reject in the grid, full record panel), Your rules (plain English → AI draft → approve as a new mandate version),
  Proof (bars read from committed runs, fee comparison, receipt check with a tamper button, log check). Design checked
  with Hallmark sloplint: 0 FAIL / 0 REFLEX, 2 waivers recorded. Review: [review-2026-11-08-ui.md](review-2026-11-08-ui.md).
- **Type (Aaron, 17:23): "Wide steel"**: Michroma (wordmark and short headings, matching the logo's lettering) +
  Reddit Sans (everything else; tabular figures for money and timings). Two families, both SIL OFL, self-hosted with
  AG Grid Community 32.3.3 (MIT) under `web/static/vendor/` so the judge demo depends on no CDN.
- **Decision trace timings:** the engine now records each layer's time and findings (`trace`), shown in the UI.
  Logic unchanged (all tests and frozen-set behaviour identical); catalogue lookup timed in the flow.
- **D14 built:** `RecordedFirstLLM` replays recorded real answers labelled "recorded <date>" with the latency measured
  at recording; new input goes live. Recording waits for the quota reset (`scripts/windows/record_demo_answers.bat`).
- **D14, part approved (Aaron, 17:04): no paid AI tier.** The 5 scripted demo scenarios use real model answers recorded once
  (after the quota resets) and replayed, labelled on screen with model and date; anything new (pasted pages, typed
  rules) calls the AI live. Still open: daily cap / per-visitor limit and a backup model. Rejected: extra Google
  accounts for more free quota (against Google's terms; risk of losing the key during judging).

## 8 Nov 2026 — Core guard + held-out look #1

- **Catalogue v2 (harder, test-only, frozen before running):** rules and detector caught 0/28; with the AI 27/28,
  0 severe misses, 0/54 false blocks, 9.3% step-ups. All pre-registered v2 expectations met; the AI layer earns its
  place on v2. Weak spots recorded: most natural injections held rather than blocked; one detector false positive.

- **Held-out look #2 (AI):** 3 pass marks met, 3 not (step-ups 20%, keep-a-layer, AI latency), reported as written.
- **D12 (Aaron): AI check stays before PayPal**, a recorded deviation from the latency fallback → ADR-0006 amendment.

- **AI layer live (Gemini, `gemini-3.5-flash-lite`)** after 4 fixes in 20 minutes: closed model, timeout minimum,
  a hallucinated "followed the page" claim, and slow "thinking". Full record: [ai-integration-log.md](ai-integration-log.md).

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
## 10 Nov 2026 (late afternoon): live refund check passed
- **What:** on the live site, purchase `pay_95f9ebd6f07e40b4` ($98, capture `5E914626V1971323N`). Aaron refunded $10, then $88, in PayPal's sandbox dashboard.
- **Result:** each `PAYMENT.CAPTURE.REFUNDED` was verified by PayPal and moved the status captured → partially_refunded → refunded; the budget got $98 back; webhook counts 4 verified / 0 duplicate / 0 rejected / 0 unmatched; audit chain verifies (6 entries).
- **Still open:** an earlier test purchase (16:29 SA) was missing 11 minutes later. Cause not established (a session reset during the test steps vs a server restart). Not a refund issue; watch it during the video recording.
- **Updated:** README limits line and threat-model R2 no longer say "pending".

## 10 Nov 2026 (evening): freeze after submission; v2 only after winners are announced (Aaron)
- **Decision:** everything submitted on 12 Nov (repo, README, video, hosted demo) stays frozen until the winners are announced (~15 Dec, end of judging). No work on AgentGuard until then; Aaron studies for CLF-C02 (30 Nov). Same path as LedgerLens after the Meta hackathon.
- **Options considered:** (a) keep improving `main` after submission; (b) work on a `v2` branch during judging; (c) full freeze until results.
- **Trade-offs:** (c) loses ~5 weeks of build time, but protects the exam, keeps the judged version exactly as submitted (Devpost rules s.5) and keeps the hosted demo stable for judges.
- **After results:** tag `v1.0-hackathon`, then v2 (AWS + Bedrock with IaC, provider bake-off, OpenTelemetry, contract tests, Disputes API, evaluation notebook, case study) and a separate portfolio video. The hackathon video is never replaced.

## 10 Nov 2026 (evening): why demo purchases disappeared (found)
- **Cause:** every push to `main` redeploys Render; demo sessions are in-memory SQLite, so a redeploy wipes them. Evidence: after pushes `6966aa7` and `03b77ee` the live site had 0 payments and all webhook counts at 0 (counts are process-wide, so they only reset on a restart).
- **Decision:** no storage change before submission (Render free has no persistent disk; a rebuild two days before the deadline is the larger risk). Instead: footer note on the page, README limitation linked to `docs/production-gaps.md`, refund check preserved in `evidence/live_checks/`. After submission there are no pushes (freeze), so judges only lose data on a platform restart.
- **Also added:** `docs/production-gaps.md` (demo vs production table and v2 plan) from the recruiter/payments-engineer review.

## 10 Nov 2026 (evening): shadow mode built (Aaron: "yes"; scope "judgement checks only") → ADR-0010
- **Decision:** a mandate can be set to `shadow`. The buyer's hard limits (rules + catalogue blocks) still act; the detector, AI, price and claim checks are only logged as "would have held / asked / blocked". Enforce stays the default.
- **Options considered:** shadow relaxes everything; judgement checks only (chosen); add an advisory mode too.
- **Trade-offs:** measures false asks on real traffic without risking spend outside the buyer's limits; but in shadow an injection attack inside the limits succeeds (labelled on the console), and an AI outage is logged instead of asked.
- **Reasoning:** AgentGuard is the payment path, so "relax everything" would mean no guard; the buyer's own limits are facts, not AgentGuard's judgement, so there is nothing to measure by relaxing them.
- **Fingerprint:** "enforce" is left out of the canonical JSON so pre-10-Nov fingerprints still verify; receipts embed the mandate exactly as hashed.
- **Not a metric:** behaviour checked by unit tests (11 new) and a local run against FakePayPal with a fake AI; no live measurement.
- **Follow-up (same evening, Aaron):** winners' products had "nothing hanging", so shadow mode must be complete or hidden. Completed: shadow report endpoint (buyer only), banner with running tally on every screen, switch-back button, README "How it works" step 5, threat-model T6 (agent can't switch mode). Not added: advisory mode, per-check shadow (roadmap).
- **Disclosure for the agent experiment (eval/agent_runs/PLAN.md):** these commits were pushed (and the live guard redeployed) at ~19:30 SA on 10 Nov, between run sets: runs before this used `e96ab27`; G3 runs 7+ and G4 use the shadow-mode code. Enforce mode (what the experiment uses) is unchanged: all 201 earlier tests pass unchanged; shadow paths only run when a mandate is set to shadow. Aaron agreed to push in the gap left by Google 503 errors.

## 10 Nov 2026 (night): second APIMatic Context Plugin review → 3 fixes
- **Decision:** fix G1 (typed `ErrorException` first), G2 (honest no-token message: payment not sent), W3 (drop cached webhook token on 401, retry once); document G3/G4/W2/W4; defer a startup token check to v2. Full review and response: `docs/apimatic-review-2026-11-11.md`.
- **Options considered:** fix all nine; fix the three with a real failure mode; document only.
- **Trade-offs:** three small changes on the money and webhook paths 14 h before code freeze, each with a test; the rest have no effect on today's live paths.
- **Reasoning:** G2 would point an operator at the wrong cause during a PayPal outage; W3 would leave verification down for hours after a secret rotation; G1 makes an SDK upgrade visible. None changes what gets charged.
- **Source:** Aaron installed the plugin (`npx context-plugins install https://github.com/paypaldev/server-sdk-context-plugin-preview`; no APIMatic subscription needed, per APIMatic's reply) and ran the review in Claude Code on his laptop.

## 11 Nov 2026: planned-vs-built reconciliation (Aaron: "make sure what we decided is what we've done")
- Every commitment in the brief, ADRs and decision log checked against code and evidence → `docs/planned-vs-built.md`.
- **Silent gaps found and now documented:** PostgreSQL never built (ADR-0007 amended); buyer approval on PayPal's page
  (JS SDK v6) not built; MCP proxy over PayPal's toolkit replaced by our own MCP server; AG Grid extras (grouping,
  risk renderer, master/detail, feedback labels) not built; MLflow not used; Pay Later rule, runbook, parsing-accuracy
  and variance metrics not built. Already documented before: anomaly model, bake-off, AWS, OTel, advisory mode,
  auto-void, Disputes API, refund guard, Postman, LLM-as-judge, p95 miss.
- **Verified:** all 57 tests cited in the threat model exist; README numbers match `interview-prep/METRICS.md`.
- **Rule from now on:** no public claim unless it is in the "Built" table of that file.

## 11 Nov 2026 (afternoon): Channel3 product identity check (Aaron: "option A")
- **Decision:** the free Channel3 product lookup the price check already makes now also returns the product's real title
  and brands; if the shop's listing names a different brand, model code or product, the buyer is asked first
  (`listing_mismatch`). New demo scenario *Mislabelled listing* (synthetic: a real Channel3 product sold under a made-up
  "Aura Studio Pro" name at its normal price, so only this check can notice).
- **Options considered:** A, product identity via Channel3 (chosen); B, AG Studio shadow-report dashboard (new
  commercial library on a trial licence, 1+ day, high risk the day before the deadline); no code change.
- **Trade-offs:** about 4 hours and one more scenario, the day before the deadline; it strengthens the main idea ("did
  the buyer mean this?") and the Channel3 sponsor case. It can only ask, never block; no claim when Channel3 is down.
- **Reasoning:** the AI intent check judges the shop's title; if the shop's title is false, the AI is judging a lie. An
  independent catalogue is the only source in the system that doesn't come from the shop or the agent.
- **Not a metric:** 6 unit tests; checked on the real snapshot (5 honest listings match, only the relabelled one is
  flagged); not part of the frozen attack sets, so no catch rate is claimed.
- **Bug found on the way:** with no Gemini key, recorded demo answers were looked up under NoAI's model name, so none
  matched and every scenario fell back to "ask". This was there before today; fixed and covered by a regression test that
  fails on the old code. It matters for the "remove the key on Render" option for Gemini's EU/UK terms.

## 11 Nov 2026 (afternoon): release-candidate checks before the code freeze
- **Every setting test** (`tests/unit/test_settings_matrix.py`, 6 tests): all six demo scenarios in each setting a judge
  could meet: key on, key removed (recorded answers only), Channel3 up / down / off, AI off, shadow mode. Checks the
  README's promises (normal always captured; poisoned and agent-lies never reach PayPal; inflated never paid silently;
  mislabelled asks whenever Channel3 answers; recorded answers replay without a key).
- **Found by it, stated, not a bug:** with AI off (or a stand-in AI) the out-of-stock swap is captured, because only
  the AI layer catches that in-limit attack. That is the rules-only gap the evaluation measures (rules alone 0/75).
- **Display fix:** the Market step showed "under 1 ms" while Channel3's time is counted in the Shop records step; it now
  says "with shop records" (we don't publish Channel3 timings, their terms, sources S9).
- **README:** new "Sponsor tools, and the job each one does" (Channel3, AG Grid, APIMatic, Render). A draft line
  claiming "CI must pass before Render deploys" was wrong (`autoDeploy: true` deploys on push) and was corrected before
  commit.
- **Process from here:** release-candidate tag → independent review in a separate chat (Fable 5.2) → fix real findings
  only → final live check → code freeze; after that, documents only.

## 11 Nov 2026 (evening): independent review of release candidate `e21df58` → fixes and corrections
- **Review:** a separate model (Fable 5.2, new chat, prompt in the planning folder) reviewed `e21df58` from a fresh clone:
  16 findings, 17 claims checked. Every finding was checked against the code before acting.
- **Fixed, each with a regression test that fails on `e21df58`** (`tests/unit/test_review_fixes.py`, 14 tests):
  #1 per-product quantity across cart lines; #2 budget below spent → 409, nothing changes; #4/#5/#14 atomic status claim
  (two approves, approve vs reject, webhook mid-capture); #7 no approval under changed rules, `custom_id` = judged
  fingerprint; #8 sessions only created by the page's session call, rate-limited; #10 agent reply = agent view;
  #12 idempotency race returns the same payment; #13 PENDING authorisation = unknown, reservation kept; #15 rate-limit
  key prefers `CF-Connecting-IP`; #5 front end says what actually happened.
- **Found by us while testing the races (not in the review):** store reads didn't take the lock the writes use, so a read
  interleaved with another thread's transaction on the shared SQLite connection could return "no such payment". Fixed.
- **Reworded, behaviour unchanged:** #3 `page_id` optional (requiring it could change the behaviour behind the published
  agent runs, whose records don't show whether the agent cited the page; T2 now Partial); "signed mandate" →
  "fingerprinted mandate" (only receipts are signed); "reused on retries" → what actually happens.
- **Documented as limits:** #6 one-pair-per-order, not across orders (M9 planned); #9 unknown outcome waits for the
  webhook; #11 detector phrasings the AI layer must catch.
- **Disclosure, agent experiment (G1 normal shopping):** 10 completed runs over 7 of 10 planned slots. Slots 3, 4 and 5
  each completed twice: after Google 503 errors the harness was resumed from slot 3, which re-ran 4 and 5 although they
  had succeeded. PLAN.md allows repeating only errored runs, so this is a deviation. All 10 runs were approved and paid
  with 0 false blocks; README now says "all 10 completed runs (7 of 10 slots)" instead of "10/10". The other totals were
  rechecked and stand: 34 completed runs, 31 of 40 slots, 0 harmful payments.
- **Test count:** 250 as CI runs them (`--all-extras`); a plain `uv sync` skips the 4 MCP tests (246). Coverage 94%.

## 11 Nov 2026 (night): public demo runs without a live model (option C) — freeze exception
- **Decision (Aaron):** no paid Gemini key, so `GEMINI_API_KEY` is removed from Render (the free tier's terms don't
  cover judges in the EU, UK or Switzerland). Scenario buttons keep replaying saved real answers, labelled.
- **Freeze exception, text only:** with no key the header still said "AI: gemini-3.5-flash-lite" and "Draft my rules"
  ended in an error. `/healthz` now reports `live_ai`; the header says "AI: saved answers" and drafting is switched off
  with one line instead of an error. No decision logic changed. Test: `test_healthz_says_whether_a_live_model_answers`.
- **Video:** real-agent clips recorded before the key is removed, labelled "Real agent run"; site clips after, as judges
  will see it.
