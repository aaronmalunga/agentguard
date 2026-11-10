# Live check: refund made on PayPal, outside AgentGuard (10 Nov 2026)

Live site `agentguard-jg01.onrender.com`, PayPal sandbox. Recorded from the live API at the time, because the demo keeps
data in memory and a later redeploy wiped it (see "Why the data is gone" below).

| Step | Who / where | Result on AgentGuard |
|---|---|---|
| Purchase `pay_95f9ebd6f07e40b4`, $98.00, order `3XT71972K4520024B`, capture `5E914626V1971323N` | Claude, live page, 14:40:32 UTC | captured; `AUTHORIZATION.CREATED` + `PAYMENT.CAPTURE.COMPLETED` verified (2) |
| Refund $10.00 in PayPal's sandbox dashboard (refund `3VU21829X86214355`) | Aaron | audit seq 5, 14:49:17 UTC: `PAYMENT.CAPTURE.REFUNDED`, `verify-webhook-signature: SUCCESS`, captured → **partially_refunded**, budget +$10.00 |
| Refund $88.00 (refund `6S8046643P719904M`; PayPal time 10:17:08 EST = 15:17:08 UTC) | Aaron | audit seq 6, 15:17:31 UTC: `PAYMENT.CAPTURE.REFUNDED`, verified, → **refunded**, refunded total 9800 cents = amount paid |

After both: webhook counts 4 verified / 0 duplicates / 0 rejected / 0 unmatched; `/api/audit/verify` ok, 6 entries,
head `a8d04836b51729b7474f9489ba8b32b7b387a7b3e26ca1c151374aaf89819297`.

## Why the data is gone
Every push to `main` redeploys the Render service. Each demo session is an in-memory SQLite database, so a redeploy
wipes payments, audit entries and webhook counts. At 16:28 UTC (after pushes `6966aa7` and `03b77ee`) the site showed
0 payments and all webhook counts at 0. The same cause explains a test purchase made at 14:29 UTC that was gone at
14:40 UTC. Production needs durable storage (see `docs/production-gaps.md`).
