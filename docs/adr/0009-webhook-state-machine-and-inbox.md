# ADR-0009: PayPal webhooks drive a forward-only payment state machine through a transactional inbox

- **Status:** Accepted · **Date:** 9 Nov 2026 · **Deciders:** Aaron (direction, 21:10: "proper fixes"), Claude (design)
- **Related:** ADR-0001 (two decision points), ADR-0007 (storage, atomic budget), review W4/W5, threat model R2/M4/R1

## Context
Until 9 Nov, verified PayPal webhooks were only appended to the audit log. So a refund or chargeback made on PayPal
left AgentGuard showing "captured" and the buyer's budget still spent, and a payment stuck in `unknown` (PayPal call
timed out) was never resolved. Event IDs were de-duplicated in process memory, separately from the payment database,
so a crash between "mark seen" and "write the effect" could lose an event, and a restart forgot every ID.

## Options considered
1. **Log only (status quo).** Simple; status and budget drift from PayPal's truth.
2. **Apply each event's status directly** (last event wins). PayPal delivers late, repeated and out-of-order events
   for up to 3 days, so a late `AUTHORIZATION.CREATED` could turn a refunded payment back into "held".
3. **Forward-only state machine + transactional inbox** (chosen): a pure function maps (current status, event) to a
   move that can only go forward; the event ID, status change, budget change and audit entry are written in ONE
   database transaction.
4. **Poll PayPal for every payment** instead of trusting events. More calls, rate limits, and still needs ordering.

## Decision
Option 3. Statuses: `unknown/held → captured | voided | declined`; `captured → partially_refunded → refunded`;
`captured/partially_refunded → reversed`. Money follows: settle on capture, release on void/denial, give back to the
budget on refund/reversal (capped at what was paid). A dispute never changes money status; it flags the payment and
stores evidence (mandate fingerprint + SHA-256 of the signed receipt). A move that would go backwards is logged as
"late, status unchanged". Module: `flow/paypal_events.py` (pure); store: `apply_paypal_event` (one transaction,
`paypal_events` table, event ID as primary key).

## Consequences
- ➕ Status and budget stay true to PayPal; a repeat is caught by the database's primary key, not memory; a crash
  mid-way rolls back, so PayPal's retry is processed cleanly (`test_event_id_effect_and_audit_entry_commit_together_or_not_at_all`).
- ➕ A payment left `unknown` after a timeout resolves itself when PayPal's event arrives.
- ➖ A payment whose *authorisation* call timed out has no PayPal ID stored, so its events can't be matched yet
  (would need the order's `reference_id`; roadmap).
- ➖ Dispute evidence is prepared, not sent: PayPal's Disputes API evidence upload is unverified (T11), roadmap.
- ➖ Unmatched events are counted, not stored.
