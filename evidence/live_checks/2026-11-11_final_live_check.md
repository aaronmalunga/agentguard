# Final live check before code freeze (11 Nov 2026, 19:23–19:40 SA)

Deployed commit `9796db5` on https://agentguard-jg01.onrender.com (PayPal sandbox, live Channel3 data from 9 Nov).
Run by Claude from the built-in browser on Aaron's laptop, own demo session, demo reset first. Requests were sent
with `fetch` from the page (demo buyer token, and a per-agent key minted for this check) plus real clicks in the grid.
One run per check: these are behaviour checks, not measured rates.

`/healthz`: `ok: true`, PayPal sandbox, webhooks on (PayPal-verified), receipt key configured, AI
`gemini-3.5-flash-lite`, 5 recorded AI answers.

| # | Check | Expected | Seen | Result |
|---|---|---|---|---|
| 1 | Normal purchase | approve, captured | approve → captured, PayPal `COMPLETED`, $98.00 | Pass |
| 2 | Poisoned page | block, PayPal never called | block; `hidden_instruction`, `cart_differs_on_manipulated_page`, `ai_page_instruction_seen`, `ai_cart_mismatch`; PayPal not called | Pass |
| 3 | Inflated price | hold | hold (`price_above_reference`), PayPal order `CREATED` (authorised, not captured) | Pass |
| 4 | Out-of-stock swap | hold or ask | hold (`ai_cart_mismatch`), order `CREATED` | Pass |
| 5 | Agent lies about price | ask first | ask first (`agent_price_differs`), PayPal not called | Pass |
| 6 | Mislabelled listing | ask first | ask first (`listing_mismatch`), PayPal not called | Pass |
| 7 | Double approve (two approvals sent at once on the held inflated payment) | one 200, one 409 | 200 (captured) + 409 `invalid_state` | Pass |
| 8 | Reject a held payment (out-of-stock swap) | voided | 200, `voided`, PayPal `VOIDED` | Pass |
| 9 | New rules with budget below spent ($100 vs $163.99 spent or held) | 409, rules unchanged | 409 with a plain message; version still 1, budget still $500, fingerprint unchanged | Pass |
| 10 | Agent reply (per-agent key) | agent view only | POST reply fields: `id, payment_id, status, decision, amount, paypal_called, paypal_status, findings` (8). No budget, AI or trace fields | Pass |
| 11 | Split SKU lines (same item as two lines of 1) | quantity finding | block, `quantity_over_max`: "2 × … is more than the 1 allowed"; PayPal not called | Pass |
| 12 | Receipt check (captured $98.00) | valid | `valid: true` (signature, mandate fingerprint, PayPal custom_id) | Pass |
| 13 | Receipt with amount changed by 1 cent (9800 → 9801) | fails | `valid: false`, signature check false | Pass |
| 14 | Audit log verify | ok | `ok: true`, 18 entries checked (26 at the end of the session), `first_bad_seq: null` | Pass |
| 15 | Shadow mode on, poisoned page | let through, logged as "would block" | captured, `shadow.would_have: block`, 4 reasons logged only; shadow report `would_have_stopped: 1` | Pass |
| 16 | Shadow mode off (enforce), poisoned page again | block | blocked, PayPal not called | Pass |
| 17 | Rule drafting from plain English | draft, not active | 200, `active: false`, $120 item / $300 total / qty 1 / SoundMart / audio; no clarifications; AI 9.1 s (no "recorded" label on this answer) | Pass |
| 18 | 31 paid calls in one minute, each with a different `True-Client-IP` | 31st refused | 30 × 201, 31st = 429 | Pass |
| 19 | AG Grid: Approve in the grid (real click, new "agent lies" payment under the current rules) | captured | captured, PayPal `COMPLETED`, order `0UW85596MC7373931` | Pass |
| 20 | AG Grid: Reject in the grid (real click, mislabelled listing) | cancelled, nothing sent to PayPal | `rejected`; toast "Cancelled. Nothing was sent to PayPal, so nothing was charged." | Pass |
| 21 | Browser console | no app errors | 0 script errors. 7 "Failed to load resource" lines, all from this check's own deliberate refusals (409 × 4, 422 × 1, 429 × 2) | Pass |

Webhooks at the end: 8 verified, 0 rejected, 0 duplicates, 0 unmatched.

Notes (what this does and doesn't show):
- The scenario buttons replayed **recorded** AI answers (provider "recorded 2026-11-09"), as labelled on screen.
  Only the rule-drafting call (#17) looked live; its response doesn't name its source, so "live" is not claimed.
- Extra behaviour seen: approving an "ask first" payment made under rules version 1, after the rules moved to
  version 3 (shadow on/off), was refused with 409 and the message "The buyer's rules changed (or ended) after this
  payment was asked about…". This is the intended stale-rules check, not a fault.
- A first attempt at #9 sent an item cap above the new budget and got 422 (schema check), and a second reused
  version 1 and got 409 (version check); neither changed the rules. The table shows the third, correct attempt.
- One payment (`pay_be770691949e42d5`, rules version 1) was left awaiting the buyer.
