"""Regression tests for the independent review of release candidate e21df58 (11 Nov 2026).

Each test reproduces one finding from the review and fails on that commit. Numbers match the review table
(docs/decision-log.md, 11 Nov evening).
"""

import dataclasses
import threading
import time

from agentguard.flow import paypal_events
from tests.unit.test_web import BUYER, FakeLLM, bview, cart, client, pay

MID = "thandi-earbuds"


def _ask_first(c, key="ask-1"):
    """An 'ask first' payment: the agent's stated price differs from the shop's ($69 Pulse earbuds)."""
    r = pay(c, cart({"sku": "EB-PULSE", "quantity": 1, "claimed_price": 49.0}), key=key)
    p = bview(c, r)
    assert p["status"] == "awaiting_buyer"
    return p["id"]


def _slow(gw, name, delay=0.15):
    real = getattr(gw, name)

    def wrapped(*a, **k):
        time.sleep(delay)
        return real(*a, **k)
    setattr(gw, name, wrapped)


def _both(fn_a, fn_b):
    out = [None, None]
    ts = [threading.Thread(target=lambda i=i, f=f: out.__setitem__(i, f())) for i, f in enumerate((fn_a, fn_b))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


def test_1_quantity_limit_counts_the_same_product_across_lines():
    c, _ = client()
    r = pay(c, cart({"sku": "EB-PULSE", "quantity": 1}, {"sku": "EB-PULSE", "quantity": 1}))
    p = bview(c, r)
    assert p["status"] not in ("captured", "held") and not p["paypal_called"]
    assert any("quantity" in f["code"] for f in p["findings"]), p["findings"]


def test_2_rules_with_a_budget_below_what_is_used_are_refused_and_change_nothing():
    c, st = client()
    assert bview(c, pay(c, cart()))["status"] == "captured"              # $69 spent
    cur = st.svc.mandates[MID].model_dump(mode="json")
    r = c.post("/api/mandates", json={"mandate": {**cur, "version": 2, "budget_total_cents": 5000, "max_item_price_cents": 5000}}, headers=BUYER)
    assert r.status_code == 409 and "less than what is already spent" in r.json()["error"]["message"]
    assert st.svc.mandates[MID].version == 1                              # the old rules stay in force
    assert st.svc.store.budget(MID)["budget_cents"] == cur["budget_total_cents"]
    ok = c.post("/api/mandates", json={"mandate": {**cur, "version": 2, "budget_total_cents": 6900, "max_item_price_cents": 6900}}, headers=BUYER)
    assert ok.status_code == 201                                          # exactly what's used is allowed


def test_4_two_approves_at_once_capture_and_count_the_money_once():
    c, st = client()
    pid = _ask_first(c)
    _slow(st.svc.gw, "authorize")
    a, b = _both(lambda: c.post(f"/api/payments/{pid}/approve", headers=BUYER),
                 lambda: c.post(f"/api/payments/{pid}/approve", headers=BUYER))
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    assert st.svc.store.payment(pid)["status"] == "captured"
    assert st.svc.store.budget(MID)["spent_cents"] == 6900 and st.svc.store.budget(MID)["reserved_cents"] == 0


def test_5_approve_racing_reject_one_wins_and_the_books_match():
    c, st = client()
    pid = _ask_first(c)
    _slow(st.svc.gw, "authorize")
    a, b = _both(lambda: c.post(f"/api/payments/{pid}/approve", headers=BUYER),
                 lambda: c.post(f"/api/payments/{pid}/reject", headers=BUYER))
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    p, bud = st.svc.store.payment(pid), st.svc.store.budget(MID)
    assert p["status"] in ("captured", "rejected")
    assert bud["spent_cents"] == (6900 if p["status"] == "captured" else 0) and bud["reserved_cents"] == 0


def test_5_reject_of_a_held_payment_twice_voids_once():
    c, st = client()
    p = bview(c, pay(c, cart({"sku": "EB-ZEN2", "quantity": 1})))         # inflated: held
    assert p["status"] == "held"
    _slow(st.svc.gw, "void")
    a, b = _both(lambda: c.post(f"/api/payments/{p['id']}/reject", headers=BUYER),
                 lambda: c.post(f"/api/payments/{p['id']}/reject", headers=BUYER))
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    assert st.svc.store.payment(p["id"])["status"] == "voided" and st.svc.store.budget(MID)["reserved_cents"] == 0


def test_7_ask_first_payment_cannot_be_approved_after_the_rules_changed():
    c, st = client()
    pid = _ask_first(c)
    cur = st.svc.mandates[MID].model_dump(mode="json")
    assert c.post("/api/mandates", json={"mandate": {**cur, "version": 2}}, headers=BUYER).status_code == 201
    r = c.post(f"/api/payments/{pid}/approve", headers=BUYER)
    assert r.status_code == 409 and "rules changed" in r.json()["error"]["message"]
    p = st.svc.store.payment(pid)
    assert p["status"] == "awaiting_buyer" and not p["paypal_order_id"]    # nothing went to PayPal


def test_7_paypal_custom_id_carries_the_fingerprint_the_payment_was_judged_under():
    c, st = client()
    seen = {}
    real = st.svc.gw.authorize

    def spy(**k):
        seen.update(k)
        return real(**k)
    st.svc.gw.authorize = spy
    p = bview(c, pay(c, cart()))
    assert seen["custom_id"] == f"agentguard:{p['mandate_fingerprint']}"


def test_12_same_idempotency_key_racing_in_returns_the_same_payment_not_a_500():
    c, st = client()
    first = bview(c, pay(c, cart(), key="same"))
    real = st.svc.store.by_request_key
    st.svc.store.by_request_key = lambda k, _n=[0]: {} if (_n.__setitem__(0, _n[0] + 1) or _n[0] <= 2) else real(k)
    r = pay(c, cart(), key="same")                                        # simulates losing the insert race
    assert r.status_code == 200 and r.json()["id"] == first["id"]
    assert len(st.svc.store.payments()) == 1


def test_13_a_pending_authorization_keeps_the_reservation_as_unknown():
    c, st = client()
    real = st.svc.gw.authorize
    st.svc.gw.authorize = lambda **k: dataclasses.replace(real(**k), status="PENDING")
    p = bview(c, pay(c, cart()))
    assert p["status"] == "unknown" and st.svc.store.budget(MID)["reserved_cents"] == 6900


def test_14_a_capture_webhook_arriving_mid_capture_changes_nothing():
    plan = paypal_events.plan({"status": "capturing", "amount_cents": 6900, "currency": "USD"},
                              "PAYMENT.CAPTURE.COMPLETED", {"id": "CAP1"})
    assert plan.status is None and plan.budget is None


def test_10_agent_reply_has_no_budget_ai_or_trace():
    c, _ = client(llm=FakeLLM())
    body = pay(c, cart()).json()
    assert {"id", "payment_id", "status", "findings"} <= set(body)
    assert not {"facts", "ai", "trace", "cart", "budget_left"} & set(body)
