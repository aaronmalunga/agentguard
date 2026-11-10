# ADR-0010: Shadow mode relaxes judgement checks only, never the buyer's hard limits

- **Status:** Accepted · **Date:** 10 Nov 2026 · **Deciders:** Aaron (direction 18:39: shadow mode "yes"; scope:
  "judgement checks only"), Claude (design)
- **Related:** ADR-0006 (AI may only escalate), brief s.6/s.8 (rollout shadow → advisory → enforce),
  `docs/production-gaps.md` (rollout row)

## Context
A team adopting AgentGuard needs to know how often it would interrupt real buyers *before* it starts interrupting
them. Our false-ask numbers come from synthetic cases (held-out: 20% asked). Shadow mode lets a buyer or platform run
the full guard on real traffic, record what it would have done, and only then switch to enforce.

AgentGuard is the payment path itself (the agent never calls PayPal directly), so "shadow" here cannot mean "observe
someone else's decision": if shadow relaxed everything, a shadow mandate would have no guard at all.

## Options considered
1. **Everything is logged only** (classic fraud-rule shadow). Pure measurement, but an over-budget order or a payment
   to a shop the buyer never allowed would go through. The buyer's own limits are not AgentGuard's guess; relaxing
   them measures nothing.
2. **Judgement checks only** (chosen). Blocks from the buyer's rules (budget, shops, price cap, quantity, dates,
   currency, delivery address, revoked/stale rules) and from the shop catalogue (unknown product, out of stock) still
   act. Everything else (hidden-text detector, AI intent check, market-price hold, agent-claim mismatches, recipient
   name) is recorded as "would have held / asked / blocked" and the payment proceeds.
3. **Advisory mode as well** (warn the buyer, don't stop). Needs a notification channel the demo doesn't have; roadmap.

## Decision
Option 2. `Mandate.mode: "enforce" | "shadow"`, default enforce, part of the signed rules (a new mandate version when
it changes). Rule in `guard/decision.py`: a finding is enforced in shadow mode iff `level == "block"` and
`source in ("rules", "catalogue")`. The payment row's `level` is what was applied; `shadow_json` records
`would_have`, `applied` and the logged-only codes. The audit entry and the signed receipt carry the same record.
Fingerprint: `mode` is omitted from the canonical JSON when it is "enforce", so every mandate made before 10 Nov
keeps the fingerprint already written into its PayPal orders and receipts; receipts now embed the mandate exactly
as hashed, so the public check (SHA-256 of the embedded mandate) is unchanged.

## Consequences
- ➕ False-ask rate can be measured on real traffic without stopping a buyer; "would have" is in the tamper-evident log.
- ➕ Shadow can never spend outside the buyer's limits.
- ➖ **In shadow, a page-injection attack inside the limits succeeds** (the demo's poisoned page buys the $119 Nova
  Lite). That is the point of shadow and why enforce is the default; the console labels every such payment
  "Shadow: would ask".
- ➖ An AI outage in shadow is logged, not asked (enforce still fails safe to "ask the buyer").
- ➖ No advisory mode and no per-check shadow (one switch per mandate). Roadmap.
- ➕ The result is a report, not just flags: `GET /api/mandates/{id}/shadow-report` (buyer only) counts payments
  decided in shadow, how many the full guard would have stopped, and why; the console shows it in a banner on every
  screen with a "Switch back to enforce" button (added 10 Nov after Aaron's "complete product, nothing hanging" test).
- Tests: `tests/unit/test_shadow.py` (14).
