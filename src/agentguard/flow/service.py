"""PaymentService: the only path from an agent's request to money moving.

  block      -> recorded, PayPal never called
  ask_first  -> recorded as awaiting the buyer, PayPal never called until the buyer says yes
  hold       -> budget reserved, PayPal AUTHORIZE (funds held) -> buyer approves (capture) or rejects (void, $0)
  approve    -> budget reserved, AUTHORIZE, then capture

Every PayPal call uses a request id derived from the payment id, so a retry reuses it (no double charge).
The order carries the mandate fingerprint in PayPal's custom_id (decision D2). An unknown PayPal outcome keeps
the budget reserved until it is read back (ADR-0007).
"""

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

from agentguard.flow import audit, paypal_events
from agentguard.flow.catalogue import AgentCart, Catalogue
from agentguard.flow.receipts import ReceiptSigner
from agentguard.flow.store import Store
from agentguard.guard.decision import Decision, Finding, combine, escalate
from agentguard.guard.engine import LAYERS, evaluate
from agentguard.guard.request import Payee, PaymentRequest
from agentguard.mandate import Mandate
from agentguard.money import line_total_cents
from agentguard.paypal import PayPalError, PayPalGateway

PAGE_CHECK_LIMIT = 4000   # matches agentguard.ai.intent.prompt()


class FlowError(Exception):
    pass


class PaymentService:
    def __init__(self, store: Store, gateway: PayPalGateway, *, mandates: dict[str, Mandate],
                 registry: dict[str, str], payment_source: Callable[[str], object],
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC), layers: tuple[str, ...] = LAYERS,
                 llm=None, catalogue: Catalogue | None = None, merchant_names: dict[str, str] | None = None,
                 signer: ReceiptSigner | None = None):
        self.store, self.gw, self.mandates, self.registry = store, gateway, mandates, registry
        self.payment_source, self.clock, self.layers, self.llm = payment_source, clock, layers, llm
        self.catalogue, self.merchant_names = catalogue, merchant_names or {}
        self.signer = signer or ReceiptSigner()
        self.history: dict[tuple[str, int], Mandate] = {(m.mandate_id, m.version): m for m in mandates.values()}

    # ------------------------------------------------------------------ mandates
    def activate_mandate(self, m: Mandate) -> Mandate:
        """A buyer-approved mandate becomes current. Old versions stay in history (receipts cite them)."""
        cur = self.mandates.get(m.mandate_id)
        if cur and m.version <= cur.version:
            raise FlowError(f"mandate {m.mandate_id} is already at version {cur.version}")
        self.mandates[m.mandate_id] = m
        self.history[(m.mandate_id, m.version)] = m
        b = self.store.budget(m.mandate_id)
        if not b:
            self.store.ensure_budget(m.mandate_id, m.budget_total_cents)
        elif b["budget_cents"] != m.budget_total_cents:
            self.store.set_budget(m.mandate_id, m.budget_total_cents)
        self._audit("mandate_activated", None, {"mandate_id": m.mandate_id, "version": m.version,
                                                "fingerprint": m.fingerprint(), "mandate": m.model_dump(mode="json")})
        return m

    # ------------------------------------------------------------------ live flow (D3): cart from the catalogue
    def submit_cart(self, cart: AgentCart, *, request_key: str, page_text: str = "",
                    page_source: str | None = None) -> dict:
        """The agent names products and quantities; prices, titles and the payee account come from the shop."""
        existing = self.store.by_request_key(request_key)
        if existing:
            return existing
        if self.catalogue is None:
            raise FlowError("no merchant catalogue configured")
        t0 = time.perf_counter()
        items, found, market = self.catalogue.resolve(cart.lines)
        total_ms = (time.perf_counter() - t0) * 1000
        market_ms = sum(m.get("ms", 0) for m in market if not m.get("cached"))
        cat_step = {"layer": "catalogue", "ms": round(max(total_ms - market_ms, 0), 2),
                    "codes": [f.code for f in found]}
        steps = [cat_step]
        if market:
            steps.append({"layer": "market", "ms": round(market_ms, 2), "codes": [], "checks": market})
        if len(page_text) > PAGE_CHECK_LIMIT:   # review 8 Nov F8: the AI reads the first 4,000 characters only
            found.append(Finding("page_too_long_to_check", "ask_first",
                                 f"The shop page is {len(page_text):,} characters; the AI check reads the first "
                                 f"{PAGE_CHECK_LIMIT:,}, so AgentGuard asks you instead of guessing.",
                                 "the page is shorter, or you confirm", source="detector"))
        mandate = self.mandates.get(cart.mandate_id)
        ship_to = cart.ship_to or (mandate.ship_to if mandate else None)
        if not items or ship_to is None:   # nothing real to pay for: record the refusal, PayPal never called
            if ship_to is None:
                found.append(Finding("unknown_mandate", "block", f"No mandate '{cart.mandate_id}' exists for this "
                                     "buyer.", "the agent cites a mandate the buyer actually approved"))
            d = combine(found, agent_note=cart.agent_note)
            d.trace = steps
            pid = self._new_record(request_key, cart.mandate_id, cart.mandate_version, None, 0, "USD", d,
                                   cart_json=cart.model_dump_json(), page_source=page_source, agent_id=cart.agent_id)
            return self._done("decision", self.store.update_payment(pid, status="blocked"))
        req = PaymentRequest(action=cart.action, mandate_id=cart.mandate_id, mandate_version=cart.mandate_version,
                             payee=Payee(merchant_id=cart.merchant_id,
                                         display_name=self.merchant_names.get(cart.merchant_id, cart.merchant_id),
                                         paypal_email=self.registry.get(cart.merchant_id, "unregistered")),
                             currency=mandate.currency if mandate else "USD", items=items, ship_to=ship_to,
                             agent_id=cart.agent_id, agent_note=cart.agent_note)
        return self.submit(req, request_key=request_key, page_text=page_text, pre_findings=found,
                           cart_json=cart.model_dump_json(), page_source=page_source, pre_trace=steps)

    # ------------------------------------------------------------------ agent side
    def submit(self, request: PaymentRequest, *, request_key: str, page_text: str = "",
               pre_findings: list[Finding] | None = None, cart_json: str | None = None,
               page_source: str | None = None, pre_trace: list | None = None) -> dict:
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
        trace = [*(pre_trace or []), *decision.trace]
        if pre_findings:                                   # catalogue findings (D3) can only raise the level
            decision = escalate(decision, pre_findings)
        decision.trace = trace
        amount = sum(line_total_cents(i.unit_price, i.quantity) for i in request.items)
        pid = self._new_record(request_key, request.mandate_id, request.mandate_version, mandate, amount,
                               request.currency, decision, cart_json=cart_json or request.model_dump_json(),
                               page_source=page_source, agent_id=request.agent_id)
        if decision.level == "block":
            return self._done("decision", self.store.update_payment(pid, status="blocked"))
        if decision.level == "ask_first":
            return self._done("decision", self.store.update_payment(pid, status="awaiting_buyer"))
        return self._done("decision", self._authorize(self.store.payment(pid),
                                                      capture_now=decision.level == "approve"))

    # ------------------------------------------------------------------ buyer side
    def buyer_approve(self, pid: str) -> dict:
        p = self.store.payment(pid)
        if p.get("status") == "held":
            return self._done("buyer_approved", self._capture(p))
        if p.get("status") == "awaiting_buyer":
            return self._done("buyer_approved", self._authorize(p, capture_now=True))
        raise FlowError(f"payment {pid} is {p.get('status')}, nothing to approve")

    def buyer_reject(self, pid: str) -> dict:
        return self._done("buyer_rejected", self._reject(pid))

    def _reject(self, pid: str) -> dict:
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

    # ------------------------------------------------------------------ evidence
    def receipt(self, pid: str) -> dict:
        """Signed receipt of intent for one payment (dispute evidence). Anyone can verify it with the public key."""
        p = self.store.payment(pid)
        if not p:
            raise FlowError(f"no payment {pid}")
        m = self.history.get((p["mandate_id"], p["mandate_version"]))
        chain = self.store.audit_entries()
        mine = [{"seq": e["seq"], "kind": e["kind"], "hash": e["hash"]} for e in chain if e["payment_id"] == pid]
        ai = json.loads(p["ai_json"]) if p.get("ai_json") else None
        return self.signer.sign({
            "receipt_version": 1, "issued_at": self.clock().isoformat(timespec="seconds"), "payment_id": pid,
            "mandate": m.model_dump(mode="json") if m else None, "mandate_fingerprint": p["mandate_fingerprint"],
            "mandate_version": p["mandate_version"], "facts": json.loads(p["facts_json"]),
            "amount_cents": p["amount_cents"], "currency": p["currency"], "decision": p["level"],
            "status": p["status"],
            "reasons": [{"code": f["code"], "level": f["level"], "source": f.get("source", "rules")}
                        for f in json.loads(p["findings_json"])],
            "ai": {k: ai.get(k) for k in ("model", "latency_ms")} if ai and "model" in ai else ai,
            "paypal": {"order_id": p["paypal_order_id"], "authorization_id": p["paypal_authorization_id"],
                       "capture_id": p["paypal_capture_id"], "status": p["paypal_status"]},
            "paypal_custom_id": f"agentguard:{p['mandate_fingerprint']}" if p["paypal_order_id"] else None,
            "audit": {"entries": mine, "chain_head": chain[-1]["hash"] if chain else audit.GENESIS}})

    def apply_paypal_event(self, pid: str, event_id: str, event_type: str, resource: dict) -> dict | None:
        """A VERIFIED PayPal webhook for payment `pid`: forward-only status change, budget follow-up and audit entry,
        all in one transaction with the event ID (agentguard.flow.paypal_events). None = already handled."""
        evidence = None
        if event_type == "CUSTOMER.DISPUTE.CREATED":
            # the evidence AgentGuard holds for this payment, fixed at the moment the dispute opened
            r = self.receipt(pid)
            evidence = {"mandate_fingerprint": r["receipt"]["mandate_fingerprint"],
                        "receipt_sha256": hashlib.sha256(audit.canonical(r).encode()).hexdigest(),
                        "receipt_key_id": r["receipt"].get("key_id"), "receipt_url": f"/api/payments/{pid}/receipt",
                        "submitted_to_paypal": False}
        data = {"event_id": event_id, "event_type": event_type, "resource_id": resource.get("id")
                or resource.get("dispute_id"), "paypal_status": resource.get("status"),
                "verified": "PayPal verify-webhook-signature: SUCCESS"}
        return self.store.apply_paypal_event(event_id, event_type, pid,
                                             lambda p: paypal_events.plan(p, event_type, resource, evidence),
                                             data, audit.link)

    def verify_audit(self) -> dict:
        return audit.verify(self.store.audit_entries())

    # ------------------------------------------------------------------ internals
    def _new_record(self, request_key, mandate_id, version, mandate, amount, currency, d: Decision, **extra) -> str:
        pid = "pay_" + uuid.uuid4().hex[:16]
        self.store.insert_payment(
            id=pid, request_key=request_key, mandate_id=mandate_id, mandate_version=version,
            mandate_fingerprint=mandate.fingerprint() if mandate else None, amount_cents=amount, currency=currency,
            level=d.level, status="deciding", findings_json=json.dumps([asdict(f) for f in d.findings]),
            facts_json=json.dumps(d.verified_facts), agent_note=d.agent_note,
            ai_json=json.dumps(d.ai_call) if d.ai_call else None, trace_json=json.dumps(d.trace), **extra)
        return pid

    def _audit(self, kind: str, pid: str | None, data: dict) -> dict:
        return self.store.append_audit(kind, pid, audit.canonical(data), audit.link)

    def _done(self, kind: str, p: dict) -> dict:
        """Every state change ends here: one hash-chained audit entry with what was decided and what PayPal said."""
        self._audit(kind, p["id"], {
            "status": p["status"], "level": p["level"], "amount_cents": p["amount_cents"], "currency": p["currency"],
            "mandate_id": p["mandate_id"], "mandate_version": p["mandate_version"],
            "mandate_fingerprint": p["mandate_fingerprint"],
            "rules_fired": [f["code"] for f in json.loads(p["findings_json"])],
            "ai": json.loads(p["ai_json"]) if p.get("ai_json") else None, "agent_id": p.get("agent_id"),
            "page_source": p.get("page_source"),
            "paypal": {k: p[k] for k in ("paypal_order_id", "paypal_authorization_id", "paypal_capture_id",
                                         "paypal_status", "paypal_debug_id")}})
        return p

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
