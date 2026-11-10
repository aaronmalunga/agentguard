# Live check: shadow mode (10 Nov 2026, 19:33 SA / 17:33 UTC)

- **Where:** https://agentguard-jg01.onrender.com after deploy of `51f6cf0` (CI green). `/healthz`: PayPal sandbox,
  AI `gemini-3.5-flash-lite`, Channel3 live prices, webhooks on (PayPal-verified), receipt key configured.
- **How:** `fetch` from the live page in the built-in browser, demo buyer token, one demo session.
- **Note:** the demo scenarios use recorded Gemini answers from 9 Nov (labelled "recorded 2026-11-09" on screen and in
  the API), so this checks shadow mode's behaviour, not a fresh AI call.

| Step | Result |
|---|---|
| Switch rules to shadow (new version) | HTTP 201 |
| Normal purchase | captured, PayPal order `05B80433SD273083S`, would_have approve |
| Poisoned page | **captured**, PayPal order `5CS976874D174041X`, would_have **block** (hidden_instruction, ai_page_instruction_seen, ai_cart_mismatch, cart_differs_on_manipulated_page logged only) |
| Inflated price | captured, PayPal order `62J33703N72528636`, would_have **hold** (price_above_reference) |
| Shadow report | decided_in_shadow 3, would_have_stopped 2 (hold 1, block 1), blocked by hard limits 0 |
| Receipt of the poisoned payment | valid: signature, mandate fingerprint (mandate carries `mode: shadow`), PayPal custom_id all true; receipt carries the shadow record |
| Switch back to enforce | HTTP 201 |
| Poisoned page again, enforce | **blocked, PayPal never called**, no shadow record |
| Audit chain | ok, 9 entries checked, first_bad_seq none |

Live site left in **enforce** mode. Demo data is in memory and resets on the next deploy.
Accessibility (axe) was run on a local server with the same code, not on the live site (the live CSP blocks
injecting axe, as intended): `evidence/accessibility/2026-11-10_axe_local.json`.
