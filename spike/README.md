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

# Spike v2 (14 Oct 2026, 19:29)

`spike_v2.py`: refunds, shipment tracking, authorization window. Same safety rules as stage 0.

| Step | Result |
|---|---|
| Authorization window (card) | ✅ `expiration_time` = create + **29 days** |
| Reauthorize immediately | ✅ refused: `REAUTHORIZATION_TOO_SOON`, "only allowed **once** from Day 4 to Day 29" |
| Seller protection on card authorization | ℹ️ `NOT_ELIGIBLE` |
| Add tracking (Orders v2 `/track`) | ✅ tracker `SHIPPED`; ID = `{capture_id}-{tracking_number}` |
| Replay tracking, same `PayPal-Request-Id` | ✅ HTTP 200, no duplicate tracker |
| Partial refund $10 | ✅ `COMPLETED` |
| Replay refund, same `PayPal-Request-Id` | ✅ same refund ID (no double refund) |
| Over-refund ($35 of $30 remaining) | ✅ refused: `REFUND_AMOUNT_EXCEEDED` |
| Refund remainder | ✅ capture status `REFUNDED` |
| Cancel tracker (PATCH status) | ✅ HTTP 204 |

Sandbox latency: 1.2–3.5 s per PayPal call.
