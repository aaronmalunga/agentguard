# AgentGuard — agent spending controls, built on PayPal

> **Status: early development (hackathon v1, started 14 Oct 2026).** PayPal **sandbox only** — no real money moves.
> Independent project; not affiliated with or endorsed by PayPal. Entry to the PayPal AI Hackathon 2026.

AI agents can now pay on people's behalf. When an agent buys something its owner never wanted, the payment was
*authorized* (the agent had permission) but not *intended*. PayPal's own merchant research says liability for disputed
agent purchases is "in flux" ([sources](docs/sources.md#s1)).

**AgentGuard is a policy-and-risk layer between an AI agent and PayPal.** For every agent-initiated payment it decides —
**approve, ask the human, or block** — explains why in plain English, and keeps a tamper-evident record of what the human
actually intended (a signed, AP2-style mandate).

## How it works (target design)

1. **Mandate** — the human states what the agent may buy (budget, categories, price ceilings, frequency, expiry) and approves it through PayPal.
2. **Before authorization** — clear violations (broken rule, hidden-instruction injection, cart that doesn't match the mandate) are **blocked before anything is sent to PayPal**.
3. **Before capture** — uncertain cases are **authorized and held**; the human approves (**capture**) or rejects (**void**).
4. **Audit** — every decision is logged with its reason; the review console (AG Grid) shows held and blocked payments.

Why two decision points: see [ADR-0001](docs/adr/0001-two-decision-points.md).

## What's proven so far (sandbox, 14 Oct 2026)

| Capability | Result |
|---|---|
| Authorize → capture; authorize → void | ✅ |
| Idempotent capture (same `PayPal-Request-Id` → same capture, no double charge) | ✅ |
| Saved payment method (Vault) charged with no cardholder present | ✅ |
| Declined payment returns HTTP 201 with authorization `DENIED` (status must be checked, not HTTP code) | ✅ |

Evidence: [`spike/`](spike/). Plan and progress: [decision log](docs/decision-log.md).

## Documentation

- [Evidence & sources](docs/sources.md) — every external claim, with publisher, date, link and limits
- [Decision log](docs/decision-log.md) — every pivot and change, dated
- [Architecture decision records](docs/adr/)

## Run the Stage 0 spike

```bash
# 1. Create a PayPal developer sandbox app (US business account) and copy .env.example to .env
#    (keep .env outside version control — it is git-ignored)
# 2. Python 3.10+ (standard library only)
python spike/stage0_spike.py
```

## Limitations (honest by design)

- Sandbox only; synthetic data; AP2-*style* mandates (not the full AP2 protocol).
- Hackathon v1 — not production software.

## AI usage

- **In the product:** *(to be completed as built — models and their roles)*
- **To build it:** Claude (Anthropic) assisted with research, code and documentation. Design decisions, evaluation and final review by Aaron Malunga.

## License

[Apache-2.0](LICENSE). See [NOTICE](NOTICE).
