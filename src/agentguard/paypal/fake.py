"""A stateful fake of the PayPal sandbox endpoints AgentGuard uses ("service virtualisation").

It plugs in UNDER the PayPal SDK as a `requests` transport adapter, so the SDK's real serialisation,
deserialisation and error mapping still run (the pattern the PayPal Server SDK Context Plugin's testing skill
recommends). Used by unit tests, keyless CI and the no-keys demo mode.

It copies the behaviours we PROVED in the real sandbox (spike/, 14 Oct and 5 Nov 2026):
- AUTHORIZE orders with a card come back already authorised (HTTP 201, authorisation CREATED).
- A card named CCREJECT-REFUSED is declined: still HTTP 201, but authorisation status DENIED.
- Same PayPal-Request-Id => same order / same capture (no double charge).
- A second capture with a NEW request id => 422 AUTHORIZATION_ALREADY_CAPTURED.
- Void => VOIDED. Vault "ON_SUCCESS" returns a vault id; that id can be charged with no buyer present.
It is NOT PayPal: amounts, IDs and timings are invented. Never report latency measured against it as PayPal's.
"""

import itertools
import json
import re
from datetime import UTC, datetime, timedelta

from requests import Response
from requests.adapters import BaseAdapter

SANDBOX = "https://api-m.sandbox.paypal.com"


class FakePayPal(BaseAdapter):
    def __init__(self, *, void_returns_no_body: bool = False):
        super().__init__()
        self.void_returns_no_body = void_returns_no_body
        self.calls: list[dict] = []           # every request: method, path, headers, body
        self.orders: dict[str, dict] = {}
        self.auths: dict[str, dict] = {}
        self.captures: dict[str, dict] = {}
        self.vault: set[str] = set()
        self._by_request_id: dict[tuple[str, str], tuple[int, dict]] = {}
        self._ids = itertools.count(1)

    # ------------------------------------------------------------------ plumbing
    def close(self):
        pass

    def _id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids):010d}FAKE"

    def _respond(self, request, status: int, body: dict | None) -> Response:
        resp = Response()
        resp.status_code = status
        resp.headers["Content-Type"] = "application/json"
        resp.headers["Paypal-Debug-Id"] = f"fake{next(self._ids):08x}"
        resp._content = b"" if body is None else json.dumps(body).encode()
        resp.url, resp.request, resp.encoding = request.url, request, "utf-8"
        return resp

    @staticmethod
    def _error(name: str, issue: str, description: str) -> dict:
        return {"name": name, "message": description, "debug_id": "fakeerror",
                "details": [{"issue": issue, "description": description}]}

    def send(self, request, **kwargs):
        path = request.url.removeprefix(SANDBOX).split("?")[0]
        headers = {k.lower(): v for k, v in request.headers.items()}
        raw = request.body.decode() if isinstance(request.body, bytes) else (request.body or "")
        body = json.loads(raw) if raw and raw.lstrip().startswith("{") else {}
        self.calls.append({"method": request.method, "path": path, "headers": headers, "body": body})
        rid = headers.get("paypal-request-id")
        if rid and (path, rid) in self._by_request_id:   # idempotent replay
            status, saved = self._by_request_id[(path, rid)]
            return self._respond(request, status, saved)
        status, out = self._route(request.method, path, body, rid)
        if rid and status < 400:
            self._by_request_id[(path, rid)] = (status, out)
        return self._respond(request, status, out)

    # ------------------------------------------------------------------ routes
    def _route(self, method, path, body, rid):
        if method == "POST" and path == "/v1/oauth2/token":
            return 200, {"access_token": "fake-token", "token_type": "Bearer", "expires_in": 32400,
                         "scope": "https://uri.paypal.com/services/payments/payment"}
        if method == "POST" and path == "/v2/checkout/orders":
            return self._create_order(body, rid)
        m = re.fullmatch(r"/v2/payments/authorizations/([^/]+)(/capture|/void)?", path)
        if m:
            auth = self.auths.get(m.group(1))
            if auth is None:
                return 404, self._error("RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID", "Authorization not found")
            if method == "GET" and not m.group(2):
                return 200, auth
            if method == "POST" and m.group(2) == "/capture":
                return self._capture(auth)
            if method == "POST" and m.group(2) == "/void":
                return self._void(auth)
        return 404, self._error("RESOURCE_NOT_FOUND", "NOT_IMPLEMENTED_IN_FAKE", f"{method} {path}")

    def _create_order(self, body, rid):
        if body.get("intent") != "AUTHORIZE":
            return 422, self._error("UNPROCESSABLE_ENTITY", "INTENT_NOT_SUPPORTED_BY_FAKE",
                                    "AgentGuard only creates AUTHORIZE orders")
        if "null" in json.dumps(body):
            return 400, self._error("INVALID_REQUEST", "INVALID_PARAMETER_SYNTAX",
                                    "Fake PayPal rejects explicit nulls (send fields or omit them)")
        source = body.get("payment_source", {}).get("card")
        if source and not rid:
            return 400, self._error("INVALID_REQUEST", "MISSING_REQUIRED_PARAMETER",
                                    "PayPal-Request-Id is required for single-step create order")
        unit = body["purchase_units"][0]
        amount = unit["amount"]
        order_id = self._id("ORD")
        auth_id = self._id("AUTH")
        now = datetime.now(UTC)
        declined = bool(source and source.get("name") == "CCREJECT-REFUSED")
        if source and source.get("vault_id") and source["vault_id"] not in self.vault:
            return 422, self._error("UNPROCESSABLE_ENTITY", "INVALID_VAULT_ID", "Unknown vault id")
        auth = {"id": auth_id, "status": "DENIED" if declined else "CREATED", "amount": amount,
                "create_time": now.isoformat(), "expiration_time": (now + timedelta(days=29)).isoformat()}
        self.auths[auth_id] = auth
        card_out = {"last_digits": "1881", "brand": "VISA"}
        if source and ((source.get("attributes") or {}).get("vault") or {}).get("store_in_vault") == "ON_SUCCESS" \
                and not declined:
            vault_id = self._id("VAULT")
            self.vault.add(vault_id)
            card_out["attributes"] = {"vault": {"id": vault_id, "status": "VAULTED"}}
        order = {"id": order_id, "intent": "AUTHORIZE", "status": "COMPLETED",
                 "payment_source": {"card": card_out},
                 "purchase_units": [{"reference_id": unit.get("reference_id", "default"), "amount": amount,
                                     "payments": {"authorizations": [auth]}}]}
        self.orders[order_id] = order
        return 201, order  # NB: 201 even when DENIED, exactly like the real sandbox

    def _capture(self, auth):
        if auth["status"] == "CAPTURED":
            return 422, self._error("UNPROCESSABLE_ENTITY", "AUTHORIZATION_ALREADY_CAPTURED",
                                    "Authorization has been previously captured")
        if auth["status"] != "CREATED":
            return 422, self._error("UNPROCESSABLE_ENTITY", "CANNOT_BE_CAPTURED",
                                    f"Authorization status is {auth['status']}")
        auth["status"] = "CAPTURED"
        capture = {"id": self._id("CAP"), "status": "COMPLETED", "amount": auth["amount"], "final_capture": True}
        self.captures[capture["id"]] = capture
        return 201, capture

    def _void(self, auth):
        if auth["status"] != "CREATED":
            return 422, self._error("UNPROCESSABLE_ENTITY", "PREVIOUSLY_CAPTURED" if auth["status"] ==
                                    "CAPTURED" else "CANNOT_BE_VOIDED", f"Authorization status is {auth['status']}")
        auth["status"] = "VOIDED"
        return (204, None) if self.void_returns_no_body else (200, auth)
