"""PaymentService: the only path from an agent's request to money moving.

  block      -> recorded, PayPal never called
  ask_first  -> recorded as awaiting the buyer, PayPal never called until the buyer says yes
  hold       -> budget reserved, PayPal AUTHORIZE (funds held) -> buyer approves (capture) or rejects (void, $0)
  approve    -> budget reserved, AUTHORIZE, then capture

Every PayPal call uses a request id derived from the payment id, so a retry reuses it (no double charge).
The order carries the mandate fingerprint in PayPal's custom_id (decision D2). An unknown PayPal outcome keeps
the budget reserved until it is read back (ADR-0007).
"""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from agentguard.flow.store import Store
from agentguard.guard.decision import Finding
from agentguard.guard.engine import LAYERS, evaluate
from agentguard.guard.request import PaymentRequest
from agentguard.mandate import Mandate
from agentguard.money import line_total_cents
from agentguard.paypal import PayPalError, PayPalGateway


class FlowError(Exception):
    pass


class PaymentService:
    def __init__(self, store: Store, gateway: PayPalGateway, *, mandates: dict[str, Mandate],
                 registry: dict[str, str], payment_source: Callable[[str], object],
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC), layers: tuple[str, ...] = LAYERS,
                 llm=None):
        self.store, self.gw, self.mandates, self.registry = store, gateway, mandates, registry
        self.payment_source, self.clock, self.layers, self.llm = payment_source, clock, layers, llm

    # ------------------------------------------------------------------ agent side
    def submit(self, request: PaymentRequest, *, request_key: str, page_text: str = "") -> dict:
        existing = self.store.by_request_key(request_key)
        if existing:                                   # the agent retried: same answer, nothing new happens
            return existing
        mandate = self.mandates.get(request.mandate_id)
        if mandate:
            self.store.ensure_budget(mandate.mandate_id, mandate.budget_total_cents)
        b = self.store.budget(request.mandate_id) if mandate else {}
        committed = b.get("spent_cents", 0) + b.get("reserved_cents", 0)
        decision = evaluate(request, mandate, now=self.clock(), registry=self.registry, spent_cents=committed,
                            page_text=page_text, layers=self.layers, llm=self.llm)
        amount = sum(line_total_cents(i.unit_price, i.quantity) for i in request.items)
        pid = "pay_" + uuid.uuid4().hex[:16]
        p = self.store.insert_payment(
            id=pid, request_key=request_key, mandate_id=request.mandate_id, mandate_version=request.mandate_version,
            mandate_fingerprint=mandate.fingerprint() if mandate else None, amount_cents=amount,
            currency=request.currency, level=decision.level, status="deciding",
            findings_json=json.dumps([f.__dict__ for f in decision.findings]),
            facts_json=json.dumps(decision.verified_facts), agent_note=decision.agent_note)
        if decision.level == "block":
            return self.store.update_payment(pid, status="blocked")
        if decision.level == "ask_first":
            return self.store.update_payment(pid, status="awaiting_buyer")
        return self._authorize(p, capture_now=decision.level == "approve")

    # ------------------------------------------------------------------ buyer side
    def buyer_approve(self, pid: str) -> dict:
        p = self.store.payment(pid)
        if p.get("status") == "held":
            return self._capture(p)
        if p.get("status") == "awaiting_buyer":
            return self._authorize(p, capture_now=True)
        raise FlowError(f"payment {pid} is {p.get('status')}, nothing to approve")

    def buyer_reject(self, pid: str) -> dict:
        p = self.store.payment(pid)
        if p.get("status") == "awaiting_buyer":
            return self.store.update_payment(pid, status="rejected")        # nothing was ever sent to PayPal
        if p.get("status") != "held":
            raise FlowError(f"payment {pid} is {p.get('status')}, nothing to reject")
        try:
            v = self.gw.void(p["paypal_authorization_id"], request_id=f"{pid}-void")
        except PayPalError as e:
            return self.store.update_payment(pid, status="unknown", paypal_debug_id=e.debug_id)
        if v.succeeded:
            self.store.release(p["mandate_id"], p["amount_cents"])
            return self.store.update_payment(pid, status="voided", paypal_status=v.status,
                                             paypal_debug_id=v.debug_id)
        return self.store.update_payment(pid, status="unknown", paypal_status=v.status)

    # ------------------------------------------------------------------ internals
    def _authorize(self, p: dict, *, capture_now: bool) -> dict:
        pid, cents = p["id"], p["amount_cents"]
        if not self.store.reserve(p["mandate_id"], cents):           # lost a race for the last of the budget
            lost = Finding("over_budget", "block", "Another payment used the remaining budget first.", None)
            return self.store.update_payment(pid, status="blocked", level="block",
                                             findings_json=json.dumps([*json.loads(p["findings_json"]),
                                                                       lost.__dict__]))
        mandate = self.mandates[p["mandate_id"]]
        try:
            a = self.gw.authorize(amount=Decimal(cents) / 100, currency=p["currency"],
                                  payment_source=self.payment_source(p["mandate_id"]), request_id=f"{pid}-auth",
                                  reference_id=pid, description="AgentGuard agent purchase",
                                  custom_id=f"agentguard:{mandate.fingerprint()}")
        except PayPalError as e:                                       # outcome unknown: keep the reservation
            return self.store.update_payment(pid, status="unknown", paypal_debug_id=e.debug_id)
        fields = {"paypal_order_id": a.order_id, "paypal_authorization_id": a.authorization_id,
                  "paypal_status": a.status, "paypal_debug_id": a.debug_id}
        if not a.authorized:                                           # e.g. DENIED (HTTP 201!)
            self.store.release(p["mandate_id"], cents)
            return self.store.update_payment(pid, status="declined", **fields)
        p = self.store.update_payment(pid, status="held", **fields)
        return self._capture(p) if capture_now else p

    def _capture(self, p: dict) -> dict:
        pid = p["id"]
        try:
            c = self.gw.capture(p["paypal_authorization_id"], request_id=f"{pid}-capture")
        except PayPalError as e:
            return self.store.update_payment(pid, status="unknown", paypal_debug_id=e.debug_id)
        if c.succeeded:
            self.store.settle(p["mandate_id"], p["amount_cents"])
            return self.store.update_payment(pid, status="captured", paypal_capture_id=c.capture_id,
                                             paypal_status=c.status, paypal_debug_id=c.debug_id)
        return self.store.update_payment(pid, status="unknown", paypal_status=c.status)
