"""PayPal webhooks: nothing is believed until PayPal verifies it; verified events land in the audit chain once."""

import json

import pytest

from agentguard.flow.paypal_events import plan
from agentguard.paypal.webhooks import WebhookVerifier, cert_url_ok, related_ids
from tests.unit.test_web import BUYER, client

HDRS = {"PAYPAL-TRANSMISSION-ID": "t-1", "PAYPAL-TRANSMISSION-TIME": "2026-11-09T16:00:00Z",
        "PAYPAL-TRANSMISSION-SIG": "c2lnbmF0dXJl", "PAYPAL-AUTH-ALGO": "SHA256withRSA",
        "PAYPAL-CERT-URL": "https://api-m.sandbox.paypal.com/v1/notifications/certs/CERT-1"}


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.ok = body, status, status < 400

    def json(self):
        return self.body

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


class PayPalStub:
    """Stands in for PayPal's OAuth and verify-webhook-signature endpoints; records what was sent."""

    def __init__(self, verdict="SUCCESS"):
        self.verdict, self.calls = verdict, []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if url.endswith("/v1/oauth2/token"):
            return Resp({"access_token": "tok", "expires_in": 32400})
        return Resp({"verification_status": self.verdict})


def test_cert_url_must_be_https_paypal():
    assert cert_url_ok("https://api-m.sandbox.paypal.com/v1/notifications/certs/X")
    assert not cert_url_ok("http://api-m.sandbox.paypal.com/x")
    assert not cert_url_ok("https://paypal.com.evil.example/x")
    assert not cert_url_ok("https://evilpaypal.com/x")


def test_verifier_posts_headers_webhook_id_and_event_and_caches_token():
    stub = PayPalStub()
    v = WebhookVerifier("id", "secret", "WH-123", session=stub)
    ev = {"id": "WH-EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"}
    assert v.verify(HDRS, ev)[0] and v.verify(HDRS, ev)[0]
    sent = [kw["json"] for url, kw in stub.calls if url.endswith("verify-webhook-signature")]
    assert sent[0]["webhook_id"] == "WH-123" and sent[0]["webhook_event"] == ev
    assert sent[0]["transmission_sig"] == "c2lnbmF0dXJl" and sent[0]["auth_algo"] == "SHA256withRSA"
    assert sum(url.endswith("/oauth2/token") for url, _ in stub.calls) == 1   # token reused


@pytest.mark.parametrize("headers, verdict, reason", [
    ({k: v for k, v in HDRS.items() if k != "PAYPAL-TRANSMISSION-SIG"}, "SUCCESS", "missing headers"),
    ({**HDRS, "PAYPAL-CERT-URL": "https://evil.example/cert"}, "SUCCESS", "certificate URL"),
    (HDRS, "FAILURE", "FAILURE"),
])
def test_verifier_rejects(headers, verdict, reason):
    stub = PayPalStub(verdict)
    ok, why = WebhookVerifier("id", "secret", "WH-123", session=stub).verify(headers, {"id": "e"})
    assert not ok and reason in why
    if reason != "FAILURE":
        assert stub.calls == []   # cheap checks never cost a PayPal call


def test_verifier_is_sandbox_only():
    with pytest.raises(ValueError):
        WebhookVerifier("id", "s", "WH", base_url="https://api-m.paypal.com")


def test_related_ids_cover_order_authorization_capture_and_refund_link():
    ev = {"resource": {"id": "CAP-1", "supplementary_data": {"related_ids": {"order_id": "ORD-1",
          "authorization_id": "AUTH-1"}}}}
    assert related_ids(ev) == {"CAP-1", "ORD-1", "AUTH-1"}
    refund = {"resource": {"id": "REF-1", "links": [{"rel": "up", "href": "https://x/v2/payments/captures/CAP-9"}]}}
    assert related_ids(refund) == {"REF-1", "CAP-9"}


def test_endpoint_off_without_webhook_id():
    c, _ = client()
    assert c.post("/api/webhooks/paypal", json={"id": "e", "event_type": "X"}).status_code == 503
    assert c.get("/healthz").json()["webhooks"] == "off"


def _captured(c, st):
    p = c.post("/api/demo/run", json={"scenario": "normal"}, headers=BUYER).json()["payment"]
    assert p["status"] == "captured"
    return p


def test_unverified_event_is_rejected_and_nothing_recorded():
    c, st = client(webhook_verifier=WebhookVerifier("id", "s", "WH", session=PayPalStub("FAILURE")))
    p = _captured(c, st)
    before = len(st.svc.store.audit_entries())
    ev = {"id": "WH-EVT-9", "event_type": "PAYMENT.CAPTURE.REVERSED", "resource": {"id": p["paypal_capture_id"]}}
    r = c.post("/api/webhooks/paypal", json=ev, headers=HDRS)
    assert r.status_code == 400 and r.json()["error"]["code"] == "unverified"
    assert len(st.svc.store.audit_entries()) == before
    assert c.get("/healthz").json()["webhook_counts"]["rejected"] == 1


def test_verified_event_lands_in_audit_chain_once():
    c, st = client(webhook_verifier=WebhookVerifier("id", "s", "WH", session=PayPalStub()))
    p = _captured(c, st)
    ev = {"id": "WH-EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED",
          "resource": {"id": p["paypal_capture_id"], "status": "COMPLETED"}}
    first = c.post("/api/webhooks/paypal", json=ev, headers=HDRS).json()
    assert first["matched"] and first["status"] == "captured"
    assert c.post("/api/webhooks/paypal", json=ev, headers=HDRS).json() == {"ok": True, "duplicate": True}
    hooks = [e for e in st.svc.store.audit_entries(p["id"]) if e["kind"] == "paypal_webhook"]
    assert len(hooks) == 1 and "PAYMENT.CAPTURE.COMPLETED" in hooks[0]["data_json"]
    assert c.get("/api/audit/verify").json()["ok"] is True
    other = {"id": "WH-EVT-2", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "NOT-OURS"}}
    assert c.post("/api/webhooks/paypal", json=other, headers=HDRS).json() == {"ok": True, "matched": False}


def test_malformed_body_is_400():
    c, _ = client(webhook_verifier=WebhookVerifier("id", "s", "WH", session=PayPalStub()))
    assert c.post("/api/webhooks/paypal", content=b"not json", headers=HDRS).status_code == 400


def test_webhooks_have_their_own_looser_rate_limit():
    c, _ = client(rate_per_min=1, webhook_verifier=WebhookVerifier("id", "s", "WH", session=PayPalStub()))
    codes = [c.post("/api/webhooks/paypal", content=b"x", headers=HDRS).status_code for _ in range(5)]
    assert codes == [400, 400, 400, 400, 429]     # 4x the paid-call limit, then 429 (PayPal retries later)
    assert c.post("/api/demo/run", json={"scenario": "nope"}, headers=BUYER).status_code == 422   # separate budget


# ---------------------------------------------------------------------------------------------------------------
# State machine (review W4) and transactional inbox (W5). Event bodies follow PayPal's documented webhook shapes
# (refund/reversal: a refund resource whose "up" link is the capture; dispute: disputed_transactions with
# seller_transaction_id). They are NOT captured sandbox events: refund is proven live separately (evidence/runs).

def _p(status, amount=5000, refunded=0):
    return {"status": status, "amount_cents": amount, "refunded_cents": refunded, "currency": "USD"}


def _refund(value, cap="CAP-1", rid="REF-1"):
    return {"id": rid, "status": "COMPLETED", "amount": {"value": value, "currency_code": "USD"},
            "links": [{"rel": "up", "href": f"https://api-m.sandbox.paypal.com/v2/payments/captures/{cap}"}]}


@pytest.mark.parametrize("status, event, to, budget", [
    ("held", "PAYMENT.CAPTURE.COMPLETED", "captured", ("settle", 5000)),
    ("unknown", "PAYMENT.CAPTURE.COMPLETED", "captured", ("settle", 5000)),
    ("held", "PAYMENT.AUTHORIZATION.VOIDED", "voided", ("release", 5000)),
    ("unknown", "PAYMENT.CAPTURE.DENIED", "declined", ("release", 5000)),
    ("unknown", "PAYMENT.AUTHORIZATION.CREATED", "held", None),
])
def test_events_move_status_forward_and_money_follows(status, event, to, budget):
    pl = plan(_p(status), event, {"id": "X", "status": "COMPLETED"})
    assert pl.status == to and pl.budget == budget


@pytest.mark.parametrize("status, event", [
    ("captured", "PAYMENT.AUTHORIZATION.CREATED"),   # late: arrives after the capture
    ("captured", "PAYMENT.AUTHORIZATION.VOIDED"),
    ("voided", "PAYMENT.CAPTURE.COMPLETED"),
    ("refunded", "PAYMENT.CAPTURE.COMPLETED"),
    ("held", "PAYMENT.CAPTURE.REFUNDED"),             # out of order: refund before we saw the capture
    ("blocked", "PAYMENT.CAPTURE.REVERSED"),
])
def test_a_late_or_out_of_order_event_never_moves_status_back(status, event):
    pl = plan(_p(status), event, _refund("50.00"))
    assert pl.status is None and pl.budget is None and pl.note


def test_partial_then_full_refund_and_never_more_than_was_paid():
    pl = plan(_p("captured"), "PAYMENT.CAPTURE.REFUNDED", _refund("20.00"))
    assert pl.status == "partially_refunded" and pl.budget == ("unspend", 2000) and pl.fields["refunded_cents"] == 2000
    pl = plan(_p("partially_refunded", refunded=2000), "PAYMENT.CAPTURE.REFUNDED", _refund("99.00"))
    assert pl.status == "refunded" and pl.budget == ("unspend", 3000)   # capped at what is left
    pl = plan(_p("captured"), "PAYMENT.CAPTURE.REVERSED", {"id": "REV-1", "status": "COMPLETED"})
    assert pl.status == "reversed" and pl.budget == ("unspend", 5000)   # no amount: the rest comes back


def test_dispute_flags_without_touching_money():
    pl = plan(_p("captured"), "CUSTOMER.DISPUTE.CREATED", {"dispute_id": "PP-D-1", "reason": "UNAUTHORISED",
              "status": "OPEN"}, evidence={"mandate_fingerprint": "fp"})
    assert pl.status is None and pl.budget is None and pl.fields["dispute_json"]["evidence"]["mandate_fingerprint"]


def _hooked(**kw):
    c, st = client(webhook_verifier=WebhookVerifier("id", "s", "WH", session=PayPalStub()), **kw)
    return c, st


def _send(c, eid, etype, resource):
    return c.post("/api/webhooks/paypal", json={"id": eid, "event_type": etype, "resource": resource}, headers=HDRS)


def test_refund_on_paypal_updates_status_budget_and_log_once():
    c, st = _hooked()
    p = _captured(c, st)
    spent = st.svc.store.budget(p["mandate_id"])["spent_cents"]
    half = f"{p['amount_cents'] // 2 / 100:.2f}"
    r = _send(c, "WH-R1", "PAYMENT.CAPTURE.REFUNDED", _refund(half, cap=p["paypal_capture_id"]))
    assert r.json()["status"] == "partially_refunded"
    assert _send(c, "WH-R1", "PAYMENT.CAPTURE.REFUNDED", _refund(half, cap=p["paypal_capture_id"])).json()["duplicate"]
    rest = f"{(p['amount_cents'] - p['amount_cents'] // 2) / 100:.2f}"
    assert _send(c, "WH-R2", "PAYMENT.CAPTURE.REFUNDED", _refund(rest, cap=p["paypal_capture_id"], rid="REF-2")
                 ).json()["status"] == "refunded"
    assert st.svc.store.budget(p["mandate_id"])["spent_cents"] == spent - p["amount_cents"]
    late = _send(c, "WH-L1", "PAYMENT.CAPTURE.COMPLETED", {"id": p["paypal_capture_id"], "status": "COMPLETED"})
    assert late.json()["status"] == "refunded"   # a late capture event does not undo the refund
    hooks = [json.loads(e["data_json"]) for e in st.svc.store.audit_entries(p["id"]) if e["kind"] == "paypal_webhook"]
    assert [h["event_id"] for h in hooks] == ["WH-R1", "WH-R2", "WH-L1"] and "unchanged" in hooks[-1]["note"]
    assert st.svc.verify_audit()["ok"]
    assert c.get(f"/api/payments/{p['id']}", headers=BUYER).json()["status"] == "refunded"


def test_dispute_on_paypal_flags_payment_and_attaches_signed_evidence():
    c, st = _hooked()
    p = _captured(c, st)
    dispute = {"dispute_id": "PP-D-1", "reason": "UNAUTHORISED", "status": "OPEN",
               "dispute_amount": {"currency_code": "USD", "value": "10.00"},
               "disputed_transactions": [{"seller_transaction_id": p["paypal_capture_id"]}]}
    assert _send(c, "WH-D1", "CUSTOMER.DISPUTE.CREATED", dispute).json()["matched"]
    got = c.get(f"/api/payments/{p['id']}", headers=BUYER).json()
    assert got["status"] == "captured" and got["dispute"]["dispute_id"] == "PP-D-1"
    ev = got["dispute"]["evidence"]
    receipt = c.get(f"/api/payments/{p['id']}/receipt", headers=BUYER).json()
    assert ev["mandate_fingerprint"] == receipt["receipt"]["mandate_fingerprint"] and len(ev["receipt_sha256"]) == 64
    assert ev["submitted_to_paypal"] is False   # Disputes API submission is roadmap (T11), and says so
    _send(c, "WH-D2", "CUSTOMER.DISPUTE.RESOLVED", {**dispute, "status": "RESOLVED",
          "dispute_outcome": {"outcome_code": "RESOLVED_SELLER_FAVOUR"}})
    got = c.get(f"/api/payments/{p['id']}", headers=BUYER).json()["dispute"]
    assert got["outcome"] == "RESOLVED_SELLER_FAVOUR" and got["evidence"]["receipt_sha256"] == ev["receipt_sha256"]


def test_event_id_effect_and_audit_entry_commit_together_or_not_at_all():
    """Transactional inbox: if anything fails mid-way, the event ID is not kept, so PayPal's retry is processed."""
    c, st = _hooked()
    p = _captured(c, st)
    store = st.svc.store

    def boom(_payment):
        raise RuntimeError("crash between reading and writing")
    before = len(store.audit_entries())
    with pytest.raises(RuntimeError):
        store.apply_paypal_event("WH-X", "PAYMENT.CAPTURE.REFUNDED", p["id"], boom, {}, lambda *_: "h")
    assert len(store.audit_entries()) == before and store.payment(p["id"])["status"] == "captured"
    r = _send(c, "WH-X", "PAYMENT.CAPTURE.REFUNDED", _refund("1.00", cap=p["paypal_capture_id"]))
    assert r.json()["status"] == "partially_refunded"   # the retry is not mistaken for a duplicate
