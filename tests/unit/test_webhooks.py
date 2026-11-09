"""PayPal webhooks: nothing is believed until PayPal verifies it; verified events land in the audit chain once."""

import pytest

from agentguard.paypal.webhooks import SeenEvents, WebhookVerifier, cert_url_ok, related_ids
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


def test_seen_events_dedupes_and_stays_bounded():
    s = SeenEvents(size=2)
    assert s.first_time("a") and not s.first_time("a")
    s.first_time("b"), s.first_time("c")
    assert s.first_time("a")   # oldest forgotten


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
    assert c.post("/api/webhooks/paypal", json=ev, headers=HDRS).json() == {"ok": True, "matched": True}
    assert c.post("/api/webhooks/paypal", json=ev, headers=HDRS).json() == {"ok": True, "duplicate": True}
    hooks = [e for e in st.svc.store.audit_entries(p["id"]) if e["kind"] == "paypal_webhook"]
    assert len(hooks) == 1 and "PAYMENT.CAPTURE.COMPLETED" in hooks[0]["data_json"]
    assert c.get("/api/audit/verify").json()["ok"] is True
    other = {"id": "WH-EVT-2", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "NOT-OURS"}}
    assert c.post("/api/webhooks/paypal", json=other, headers=HDRS).json() == {"ok": True, "matched": False}


def test_malformed_body_is_400():
    c, _ = client(webhook_verifier=WebhookVerifier("id", "s", "WH", session=PayPalStub()))
    assert c.post("/api/webhooks/paypal", content=b"not json", headers=HDRS).status_code == 400
