# AGENTS.md: how to work on AgentGuard (for people and AI coding assistants)

Read this first. It's the portable rulebook: any IDE or assistant (Claude Code, Cursor, Codex, Copilot...) should
follow it. History and decisions: `docs/PROJECT_CONTEXT.md`.

## What this is
AgentGuard checks that an AI agent's payment is what the buyer meant, before money moves on PayPal. The agent asks,
AgentGuard decides (approve / hold / ask first / block), PayPal moves the money. **PayPal sandbox only.**

## Run it
```bash
uv sync                                   # Python 3.12, locked deps
uv run pytest                             # all unit tests, no keys needed (FakePayPal, fake LLM)
uv run ruff check src tests eval scripts  # lint (CI runs both)
uv run python eval/run_eval.py            # evaluation on the dev split, no AI calls
```
With keys in `../.env` or `.env` (`PAYPAL_ENV=sandbox`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `GEMINI_API_KEY`):
`scripts/smoke_gateway.py`, `scripts/smoke_flow.py`, `scripts/smoke_ai.py` (live checks); `eval/run_eval.py --ai`.
Windows one-click versions: `scripts/windows/*.bat`.

## Layout
`src/agentguard/` · `config.py` (sandbox-only settings) · `money.py` (integer cents) · `mandate.py` (immutable,
versioned, fingerprinted) · `paypal/` (gateway on `paypal-server-sdk`, `fake.py` = FakePayPal, `testing.py` = sandbox
test card, tests/scripts only) · `guard/` (`rules.py`, `detector.py`, `engine.py`, `decision.py`, `request.py`) ·
`ai/` (`llm.py`, `intent.py`, `mandate_parser.py`, `cache.py`) · `flow/` (`service.py`, `store.py`).
`eval/` (catalogues, runner) · `evidence/` (every measured run) · `docs/` (ADRs, plans, logs) · `scripts/`.

## Non-negotiable rules
1. **Sandbox only.** Never point anything at live PayPal. Settings and the gateway both refuse.
2. **Money is integer cents** (`agentguard.money`). Never floats in a decision.
3. **Payment status decides, never the HTTP code** (a decline is HTTP 201 + `DENIED`).
4. **Every money-moving PayPal call has a `PayPal-Request-Id`**, derived from the payment id so retries reuse it.
5. **AI may only escalate** (approve → hold → ask first → block). Any AI failure → ask the buyer. AI never moves money.
6. **Never trust the agent's report:** facts shown to the buyer come from AgentGuard's checks, not agent text.
7. **Card numbers never in product code** (a test enforces it). Secrets only in env vars; never in git, logs or output.
8. **Frozen test sets are never edited** (`eval/attacks/v0`, `v1`, `v2`, `v3`). New cases → new version folder,
   frozen and committed **before** any run. Tune only on **dev**. Held-out and test-only runs need `--reason` and are
   logged in `evidence/heldout_looks.jsonl`.
9. **Pre-register before measuring:** expectations and pass marks go in `docs/evaluation-plan.md` §8 first. Report
   results as written, including misses. Disclose any change informed by test data.
10. **Never invent a number.** A metric exists only if a committed run produced it (`evidence/runs/`).
11. **Record decisions the same day:** `docs/decision-log.md`; architectural ones get an ADR in `docs/adr/`;
    human approvals with date and time.
12. **Adversarial review after each build step** (`docs/review-process.md`): look for holes a sceptical reviewer would
    find; classify Fixed / Planned / Open.
13. **Real over simulated** in demos and screenshots; anything simulated is labelled.

## Commit style
Small commits; message says what and why; run `ruff` and `pytest` first. AI assistance is disclosed (trailer lines).
