# Contributing to AgentGuard

Thanks for helping. AgentGuard checks that an AI agent's payment is what the buyer meant, before money moves on
PayPal. It runs against the **PayPal sandbox only**; no real money is ever involved.

## Run it in 5 minutes (no PayPal keys needed)
```bash
git clone https://github.com/aaronmalunga/agentguard && cd agentguard
uv sync                 # Python 3.12 and locked dependencies (install uv: https://docs.astral.sh/uv/)
uv run pytest           # unit tests against FakePayPal, a stateful double of proven sandbox behaviours
```
Optional, with sandbox keys in `.env` (see `.env.example`): `uv run python scripts/smoke_gateway.py`.

## Ways to help
- **Break it.** Found a payment AgentGuard should have stopped? Open an issue with the *Attack that got through*
  template. Outside attacks are reported separately from our own catalogue, never mixed in.
- **Report a bug** with the bug template.
- **Improve docs.** If a step confused you, it will confuse others.

## Rules for code changes
- Tests for every change; `uv run ruff check src tests eval scripts` and `uv run pytest` must pass.
- Money is integer cents (`agentguard.money`), never floats.
- Payment **status** decides outcomes, never the HTTP code. Every money-moving call needs a `PayPal-Request-Id`.
- AI checks may only **add** caution (approve → ask → block); an AI error means "ask the human".
- Never edit a frozen attack catalogue (`eval/attacks/v0`, `v1`). New cases go in a new version folder.
- No secrets in code, logs, issues or screenshots. Security problems: see [SECURITY.md](SECURITY.md), not a public issue.
- Architectural changes get an ADR in `docs/adr/`.

By contributing you agree your work is licensed under [Apache-2.0](LICENSE).
