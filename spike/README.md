# Stage 0 spike (14 Oct 2026)

Throwaway script proving the PayPal behaviours AgentGuard depends on, against the **sandbox**. Not product code.
Standard library only; refuses to run unless `PAYPAL_ENV=sandbox`; never prints secrets or tokens; uses PayPal's public
sandbox test card only.

| Step | Result (14 Oct 2026) |
|---|---|
| OAuth client credentials | ✅ token valid ~9 h |
| Card order `intent=AUTHORIZE` | ✅ authorizes at creation |
| Capture | ✅ `COMPLETED` |
| Replay capture, same `PayPal-Request-Id` | ✅ same capture ID returned (no double charge) |
| Capture again, new Request-Id | ✅ refused: `AUTHORIZATION_ALREADY_CAPTURED` |
| Void | ✅ `VOIDED` |
| Vault card on success → merchant-initiated charge with `vault_id` | ✅ authorized with no cardholder present |
| Rejection trigger `CCREJECT-REFUSED` | ✅ HTTP 201 but authorization `DENIED` |

Redacted results (IDs, statuses, PayPal debug IDs only): [`results/`](results/).
