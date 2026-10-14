"""
AgentGuard - Stage 0 sandbox spike (throwaway, not product code).

Proves, against the real PayPal SANDBOX:
  1. OAuth client-credentials token
  2. Orders v2 intent=AUTHORIZE -> authorize -> capture
  3. Idempotency: replaying the capture with the SAME PayPal-Request-Id must not double-capture
  4. Authorize -> void (the guard's "block" path)
  5. Vault: save a card on a successful authorization, then charge the saved token
     with no cardholder present (merchant-initiated, stored_credential) -> the agent case
  6. A forced decline (rejection trigger) -> how a refusal looks

Safety:
  - Sandbox only: refuses to run if PAYPAL_ENV != sandbox.
  - Never prints or writes the secret or the access token.
  - Uses PayPal's public sandbox TEST card numbers only (from PayPal docs). The real
    product never handles card numbers; this is spike-only.
  - Writes a redacted summary to spike_results.json (ids, statuses, debug_ids only).

Run (Windows, from the repo root):  python spike\\stage0_spike.py
"""
import base64, json, os, sys, time, uuid, urllib.request, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = "https://api-m.sandbox.paypal.com"
RESULTS = []

def load_env(path):
    env = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def call(method, path, token=None, body=None, request_id=None, basic=None, form=None):
    headers = {"Content-Type": "application/json", "Prefer": "return=representation"}
    data = None
    if basic:
        headers["Authorization"] = "Basic " + basic
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = form.encode()
    else:
        headers["Authorization"] = "Bearer " + token
        if body is not None:
            data = json.dumps(body).encode()
    if request_id:
        headers["PayPal-Request-Id"] = request_id
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {}), r.headers.get("Paypal-Debug-Id"), round((time.time()-t0)*1000)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            j = json.loads(raw)
        except Exception:
            j = {"raw": raw[:300].decode(errors="replace")}
        return e.code, j, e.headers.get("Paypal-Debug-Id") or j.get("debug_id"), round((time.time()-t0)*1000)

def record(step, http_status, body, debug_id, ms, **extra):
    issue = None
    if isinstance(body, dict) and body.get("details"):
        d = body["details"][0]
        issue = f'{d.get("issue")}: {d.get("description")}'
    row = {"step": step, "http": http_status, "ms": ms, "debug_id": debug_id,
           "error": body.get("name") if http_status >= 400 else None, "issue": issue, **extra}
    RESULTS.append(row)
    flag = "OK  " if http_status < 400 else "FAIL"
    print(f"[{flag}] {step:<48} HTTP {http_status}  {ms}ms  " + "  ".join(f"{k}={v}" for k, v in extra.items() if v is not None) + (f"  issue={issue}" if issue else ""))

ADDRESS = {"address_line_1": "123 Test St", "admin_area_2": "San Jose", "admin_area_1": "CA",
           "postal_code": "95131", "country_code": "US"}

def card(name="Alex Rivera", vault=False):
    c = {"number": "4012888888881881", "expiry": "2030-12", "security_code": "123",
         "name": name, "billing_address": ADDRESS}
    if vault:
        c["attributes"] = {"vault": {"store_in_vault": "ON_SUCCESS"}}
    return {"card": c}

def order_body(amount, desc, payment_source):
    return {"intent": "AUTHORIZE",
            "purchase_units": [{"reference_id": "spike", "description": desc,
                                "amount": {"currency_code": "USD", "value": amount}}],
            "payment_source": payment_source}

def create_and_authorize(token, label, amount, payment_source):
    s, b, d, ms = call("POST", "/v2/checkout/orders", token, order_body(amount, label, payment_source), str(uuid.uuid4()))
    record(f"{label}: create order", s, b, d, ms, order_id=b.get("id"), status=b.get("status"))
    if s >= 400:
        return None, (None, b)
    oid = b["id"]
    auth = None
    # Card orders may come back already authorized; otherwise call /authorize.
    try:
        auth = b["purchase_units"][0]["payments"]["authorizations"][0]
    except (KeyError, IndexError):
        s, b, d, ms = call("POST", f"/v2/checkout/orders/{oid}/authorize", token, {}, str(uuid.uuid4()))
        try:
            auth = b["purchase_units"][0]["payments"]["authorizations"][0]
        except (KeyError, IndexError):
            auth = None
        record(f"{label}: authorize", s, b, d, ms, order_status=b.get("status"),
               auth_id=auth and auth.get("id"), auth_status=auth and auth.get("status"))
    else:
        record(f"{label}: authorized at create", 200, b, d, 0, auth_id=auth.get("id"), auth_status=auth.get("status"))
    vault_id = None
    try:
        vault_id = b["payment_source"]["card"]["attributes"]["vault"]["id"]
    except (KeyError, TypeError):
        pass
    return auth, (vault_id, b)

def main():
    # Credentials are looked up OUTSIDE version control: $AGENTGUARD_ENV_FILE,
    # then <repo>/.env (git-ignored), then the folder above the repo.
    candidates = [os.environ.get("AGENTGUARD_ENV_FILE"), ROOT / ".env", ROOT.parent / ".env"]
    env_path = next((Path(c) for c in candidates
                     if c and Path(c).exists() and "PAYPAL_CLIENT_ID" in Path(c).read_text(encoding="utf-8-sig")), None)
    if env_path is None:
        sys.exit("No .env found (set AGENTGUARD_ENV_FILE or see .env.example).")
    env = load_env(env_path)
    if env.get("PAYPAL_ENV", "").lower() != "sandbox":
        sys.exit("Refusing to run: PAYPAL_ENV must be 'sandbox'.")
    cid, sec = env.get("PAYPAL_CLIENT_ID"), env.get("PAYPAL_CLIENT_SECRET")
    if not cid or not sec:
        sys.exit("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET missing in .env")

    # 1. OAuth
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    s, b, d, ms = call("POST", "/v1/oauth2/token", basic=basic, form="grant_type=client_credentials")
    record("1. OAuth token", s, b, d, ms, expires_in_s=b.get("expires_in"),
           scope_count=len(b.get("scope", "").split()) if s < 400 else None)
    if s >= 400:
        return finish()
    token = b["access_token"]  # kept in memory only

    # 2+3. authorize -> capture, then replay capture with same PayPal-Request-Id
    auth, _ = create_and_authorize(token, "2. Approve path", "24.99", card())
    if auth:
        rid = str(uuid.uuid4())
        s, b, d, ms = call("POST", f"/v2/payments/authorizations/{auth['id']}/capture", token, {"final_capture": True}, rid)
        cap1 = b.get("id")
        record("2. capture", s, b, d, ms, capture_id=cap1, status=b.get("status"))
        s, b, d, ms = call("POST", f"/v2/payments/authorizations/{auth['id']}/capture", token, {"final_capture": True}, rid)
        record("3. capture REPLAY (same Request-Id)", s, b, d, ms, capture_id=b.get("id"),
               same_capture=(b.get("id") == cap1) if b.get("id") else None)
        s, b, d, ms = call("POST", f"/v2/payments/authorizations/{auth['id']}/capture", token, {"final_capture": True}, str(uuid.uuid4()))
        record("3b. capture again (NEW Request-Id)", s, b, d, ms, capture_id=b.get("id"))

    # 4. authorize -> void
    auth, _ = create_and_authorize(token, "4. Block path", "149.00", card())
    if auth:
        s, b, d, ms = call("POST", f"/v2/payments/authorizations/{auth['id']}/void", token, None, str(uuid.uuid4()))
        record("4. void", s, b, d, ms, status=(b.get("status") if b else "204 no body"))

    # 5. Vault: save on success, then merchant-initiated charge with the token
    auth, (vault_id, raw) = create_and_authorize(token, "5a. Vault-on-success", "1.00", card(vault=True))
    vstatus = None
    try:
        vstatus = raw["payment_source"]["card"]["attributes"]["vault"]["status"]
    except (KeyError, TypeError):
        pass
    record("5a. vault result", 200, {}, None, 0, vault_id_present=bool(vault_id), vault_status=vstatus)
    if auth:
        call("POST", f"/v2/payments/authorizations/{auth['id']}/void", token, None, str(uuid.uuid4()))
    if vault_id:
        src = {"card": {"vault_id": vault_id,
                        "stored_credential": {"payment_initiator": "MERCHANT",
                                              "payment_type": "UNSCHEDULED",
                                              "usage": "SUBSEQUENT"}}}
        auth, _ = create_and_authorize(token, "5b. Agent charge via vault_id", "12.50", src)
        if auth:
            s, b, d, ms = call("POST", f"/v2/payments/authorizations/{auth['id']}/void", token, None, str(uuid.uuid4()))
            record("5b. void (cleanup)", s, b, d, ms)

    # 6. forced decline via rejection trigger in the card name
    create_and_authorize(token, "6. Decline trigger", "9.99", card(name="CCREJECT-REFUSED"))
    finish()

def finish():
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / time.strftime("%Y-%m-%d_%H%M_stage0_spike_results.json")
    out.write_text(json.dumps({"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": RESULTS}, indent=2))
    print(f"\nSaved redacted results to {out}")

if __name__ == "__main__":
    main()
