"""PayPal webhooks: PayPal tells AgentGuard when a payment changes, and AgentGuard only believes it after PayPal
confirms the signature.

Why: AgentGuard learns most results straight from PayPal's response (authorize, capture, void). Webhooks add what
happens later or elsewhere: a capture that completes after review, a refund or reversal made outside AgentGuard, a
dispute. Each verified event is written to the payment's hash-chained audit log, so PayPal's own record sits next to
AgentGuard's decision.

Rules:
- Never act on an unverified event. Verification is PayPal's documented postback: POST the transmission headers, our
  webhook ID and the event to /v1/notifications/verify-webhook-signature; only "SUCCESS" passes.
- Cheap checks first (all five headers present, certificate URL on a paypal.com host), so junk never costs a PayPal
  call.
- PayPal retries for up to 3 days, so the same event can arrive more than once: de-duplicate by event ID.
- Sandbox only, like the rest of AgentGuard. The webhook ID comes from PAYPAL_WEBHOOK_ID; without it the endpoint
  is off and says so.
- Webhook Simulator events are mock events PayPal cannot verify (PayPal docs), so testing needs real sandbox events.
"""

import threading
import time
from collections import OrderedDict
from urllib.parse import urlparse

import requests

from agentguard.config import SANDBOX_HOST

HEADERS = ("paypal-transmission-id", "paypal-transmission-time", "paypal-transmission-sig", "paypal-cert-url",
           "paypal-auth-algo")
TIMEOUT_S = 10


def cert_url_ok(url: str) -> bool:
    u = urlparse(url or "")
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == "paypal.com" or host.endswith(".paypal.com"))


def related_ids(event: dict) -> set[str]:
    """Every PayPal ID in an event that could match one of our payments (order, authorization or capture)."""
    r = event.get("resource") or {}
    ids = {r.get("id")}
    rel = ((r.get("supplementary_data") or {}).get("related_ids") or {})
    ids |= {rel.get("order_id"), rel.get("authorization_id"), rel.get("capture_id")}
    for link in r.get("links") or []:   # a refund links "up" to its capture
        if link.get("rel") == "up":
            ids.add((link.get("href") or "").rstrip("/").rsplit("/", 1)[-1])
    return {i for i in ids if i}


class WebhookVerifier:
    def __init__(self, client_id: str, client_secret: str, webhook_id: str, *,
                 base_url: str = f"https://{SANDBOX_HOST}", session: requests.Session | None = None):
        if urlparse(base_url).hostname != SANDBOX_HOST:
            raise ValueError("webhook verification is sandbox only")
        self.client_id, self.client_secret, self.webhook_id = client_id, client_secret, webhook_id
        self.base_url, self.http = base_url, session or requests.Session()
        self._token, self._token_until, self._lock = "", 0.0, threading.Lock()

    def _access_token(self) -> str:
        with self._lock:
            if time.monotonic() < self._token_until:
                return self._token
            r = self.http.post(f"{self.base_url}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                               auth=(self.client_id, self.client_secret), timeout=TIMEOUT_S)
            r.raise_for_status()
            body = r.json()
            self._token = body["access_token"]
            self._token_until = time.monotonic() + max(60, int(body.get("expires_in", 300)) - 120)
            return self._token

    def verify(self, headers: dict, event: dict) -> tuple[bool, str]:
        """(verified, reason). Never raises: any failure means 'not verified'."""
        h = {k.lower(): v for k, v in headers.items()}
        missing = [k for k in HEADERS if not h.get(k)]
        if missing:
            return False, "missing headers: " + ", ".join(missing)
        if not cert_url_ok(h["paypal-cert-url"]):
            return False, "certificate URL is not a paypal.com address"
        body = {"auth_algo": h["paypal-auth-algo"], "cert_url": h["paypal-cert-url"],
                "transmission_id": h["paypal-transmission-id"], "transmission_sig": h["paypal-transmission-sig"],
                "transmission_time": h["paypal-transmission-time"], "webhook_id": self.webhook_id,
                "webhook_event": event}
        try:
            r = self.http.post(f"{self.base_url}/v1/notifications/verify-webhook-signature", json=body,
                               headers={"Authorization": f"Bearer {self._access_token()}"}, timeout=TIMEOUT_S)
            status = r.json().get("verification_status") if r.ok else f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError, KeyError) as e:
            return False, f"verification call failed ({type(e).__name__})"
        return status == "SUCCESS", f"PayPal says {status}"


class SeenEvents:
    """Event IDs already handled. Bounded, in memory (one process, like the demo)."""

    def __init__(self, size: int = 5000):
        self.size, self.ids, self._lock = size, OrderedDict(), threading.Lock()

    def first_time(self, event_id: str) -> bool:
        with self._lock:
            if event_id in self.ids:
                return False
            self.ids[event_id] = True
            while len(self.ids) > self.size:
                self.ids.popitem(last=False)
            return True
