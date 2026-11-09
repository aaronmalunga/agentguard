"""What a VERIFIED PayPal webhook event does to one payment: a forward-only state machine (review W4, 9 Nov).

PayPal sends events late, more than once and out of order (it retries for up to 3 days), so:
- A payment's status only moves FORWARD:  unknown/held -> captured | voided | declined;
  captured -> partially_refunded -> refunded;  captured/partially_refunded -> reversed.
  An event that would move it backwards (an AUTHORIZATION.CREATED arriving after the capture) is recorded in the audit
  log as "late, status unchanged" and changes nothing else.
- Money follows status: reserved money is settled on capture and released on void/denial. A refund or reversal made on
  PayPal (AgentGuard itself never refunds) gives that amount back to the buyer's budget.
- A dispute never changes the money status (the money moves later, as a reversal event). It flags the payment and
  attaches the evidence AgentGuard holds: the mandate fingerprint and the signed receipt of intent.

This module is pure (no I/O): `plan()` returns what should change; the store applies it in ONE transaction together with
the event ID and the audit entry (transactional inbox, review W5).
"""

from dataclasses import dataclass, field

from agentguard.money import to_cents

UNSETTLED = ("held", "unknown")            # money is reserved, PayPal's final answer not yet known
SETTLED = ("captured", "partially_refunded")  # money was taken and some of it can still come back


@dataclass
class Plan:
    status: str | None = None              # new status, or None = unchanged
    budget: tuple[str, int] | None = None  # ("settle" | "release" | "unspend", cents)
    fields: dict = field(default_factory=dict)
    note: str = ""                         # plain English for the audit log and the console


def _amount_cents(resource: dict, currency: str) -> int | None:
    amt = resource.get("amount") or {}
    if not amt.get("value") or (amt.get("currency_code") or currency) != currency:
        return None
    return to_cents(amt["value"])


def plan(payment: dict, event_type: str, resource: dict, evidence: dict | None = None) -> Plan:
    s, total = payment["status"], payment["amount_cents"]
    refunded = payment.get("refunded_cents") or 0

    if event_type == "PAYMENT.AUTHORIZATION.CREATED":
        if s == "unknown":
            return Plan("held", fields={"paypal_status": resource.get("status")},
                        note="PayPal confirms the authorisation; the hold stands.")
        return Plan(note="Authorisation already known; status unchanged.")

    if event_type == "PAYMENT.AUTHORIZATION.VOIDED":
        if s in UNSETTLED:
            return Plan("voided", ("release", total), {"paypal_status": "VOIDED"},
                        "PayPal voided the authorisation; reserved budget released.")
        return Plan(note=f"Void arrived while the payment is {s}; status unchanged (late or out of order).")

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        if s in UNSETTLED:
            return Plan("captured", ("settle", total),
                        {"paypal_capture_id": resource.get("id"), "paypal_status": "COMPLETED"},
                        "PayPal confirms the capture.")
        return Plan(note=f"Capture confirmation while the payment is {s}; status unchanged.")

    if event_type == "PAYMENT.CAPTURE.DENIED":
        if s in UNSETTLED:
            return Plan("declined", ("release", total), {"paypal_status": "DENIED"},
                        "PayPal denied the capture; reserved budget released.")
        return Plan(note=f"Capture denial while the payment is {s}; status unchanged.")

    if event_type in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        reversal = event_type.endswith("REVERSED")
        if s not in SETTLED:
            return Plan(note=f"{'Reversal' if reversal else 'Refund'} while the payment is {s}; recorded only "
                             "(out of order).")
        remaining = total - refunded
        cents = _amount_cents(resource, payment["currency"])
        cents = remaining if cents is None else min(cents, remaining)
        new_refunded = refunded + cents
        if reversal:
            status, note = "reversed", "PayPal reversed the payment (e.g. a chargeback), outside AgentGuard."
        else:
            status = "refunded" if new_refunded >= total else "partially_refunded"
            note = "Refunded on PayPal, outside AgentGuard."
        return Plan(status, ("unspend", cents) if cents > 0 else None,
                    {"refunded_cents": new_refunded, "paypal_status": resource.get("status")},
                    f"{note} {cents / 100:.2f} {payment['currency']} back to the buyer's budget.")

    if event_type.startswith("CUSTOMER.DISPUTE."):
        dispute = {"dispute_id": resource.get("dispute_id"), "reason": resource.get("reason"),
                   "status": resource.get("status"), "outcome": (resource.get("dispute_outcome") or {})
                   .get("outcome_code"), "amount": (resource.get("dispute_amount") or {}).get("value"),
                   "updated_by_event": event_type}
        if evidence:
            dispute["evidence"] = evidence
        what = {"CUSTOMER.DISPUTE.CREATED": "opened", "CUSTOMER.DISPUTE.UPDATED": "updated",
                "CUSTOMER.DISPUTE.RESOLVED": "resolved"}.get(event_type, "changed")
        return Plan(fields={"dispute_json": dispute},
                    note=f"Buyer dispute {what} on PayPal; evidence attached (mandate fingerprint + signed receipt).")

    return Plan(note="Event recorded; it doesn't change the payment.")
