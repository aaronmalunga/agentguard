"""
AgentGuard - Spike v2 (throwaway, not product code). 14 Oct 2026.

Question this spike answers: "Can AgentGuard's refund guard and its pre-capture
human review actually work against real PayPal sandbox behaviour?"

T9  Authorization honour period / validity
    9a. Authorize a card order and read create_time + expiration_time from PayPal
        (empirical validity window, instead of trusting conflicting docs)
    9b. Try to REAUTHORIZE immediately (docs say only allowed after the honour period)
    9c. Void (cleanup)

T8  Refunds + shipment tracking
    8a. Authorize + capture $40.00
    8b. Add shipment tracking to the order (Orders v2 /track)
    8c. Replay the same tracking call with the same PayPal-Request-Id (idempotency)
    8d. Read the order back and list its trackers
    8e. Partial refund $10.00
    8f. Replay the partial refund with the same PayPal-Request-Id (no double refund?)
    8g. Over-refund: try $35.00 when only $30.00 remains (PayPal should refuse)
    8h. Refund the remaining $30.00
    8i. Read the capture back (expect status REFUNDED)
    8j. Cancel the tracker (PATCH status=CANCELLED)

Safety (same rules as stage 0):
  - Sandbox only: refuses to run unless PAYPAL_ENV=sandbox.
  - Never prints or writes the client secret or the access token.
  - PayPal's public sandbox TEST card only.
  - Writes a redacted summary (ids, statuses, debug_ids, timings) to results/.

Run (Windows, from the repo root):  python spike\\spike_v2.py
"""
import base64, json, os, random, sys, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import stage0_spike as s0  # reuse call(), record(), card(), create_and_authorize()

call, record, RESULTS = s0.call, s0.record, s0.RESULTS


def rid():
    return str(uuid.uuid4())


def get_token():
    candidates = [os.environ.get("AGENTGUARD_ENV_FILE"), ROOT / ".env", ROOT.parent / ".env"]
    env_path = next((Path(c) for c in candidates
                     if c and Path(c).exists() and "PAYPAL_CLIENT_ID" in Path(c).read_text(encoding="utf-8-sig")), None)
    if env_path is None:
        sys.exit("No .env found (set AGENTGUARD_ENV_FILE or see .env.example).")
    env = s0.load_env(env_path)
    if env.get("PAYPAL_ENV", "").lower() != "sandbox":
        sys.exit("Refusing to run: PAYPAL_ENV must be 'sandbox'.")
    cid, sec = env.get("PAYPAL_CLIENT_ID"), env.get("PAYPAL_CLIENT_SECRET")
    if not cid or not sec:
        sys.exit("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET missing in .env")
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    s, b, d, ms = call("POST", "/v1/oauth2/token", basic=basic, form="grant_type=client_credentials")
    record("0. OAuth token", s, b, d, ms, expires_in_s=b.get("expires_in"))
    return b.get("access_token") if s < 400 else None


def money(v):
    return {"value": v, "currency_code": "USD"}


def t9_honour_period(token):
    auth, _ = s0.create_and_authorize(token, "9a. Honour-period auth", "20.00", s0.card())
    if not auth:
        return
    record("9a. authorization window", 200, {}, None, 0,
           create_time=auth.get("create_time"), expiration_time=auth.get("expiration_time"),
           seller_protection=(auth.get("seller_protection") or {}).get("status"))
    s, b, d, ms = call("POST", f"/v2/payments/authorizations/{auth['id']}/reauthorize", token,
                       {"amount": money("20.00")}, rid())
    record("9b. reauthorize immediately", s, b, d, ms,
           new_auth_id=b.get("id"), status=b.get("status"))
    s, b, d, ms = call("POST", f"/v2/payments/authorizations/{auth['id']}/void", token, None, rid())
    record("9c. void (cleanup)", s, b, d, ms)


def t8_refund_and_tracking(token):
    auth, (_, order) = s0.create_and_authorize(token, "8a. Refund path", "40.00", s0.card())
    if not auth:
        return
    order_id = order.get("id")
    s, b, d, ms = call("POST", f"/v2/payments/authorizations/{auth['id']}/capture", token,
                       {"final_capture": True}, rid())
    capture_id = b.get("id")
    record("8a. capture", s, b, d, ms, capture_id=capture_id, status=b.get("status"))
    if not capture_id:
        return

    # 8b/8c. tracking, then replay with the same Request-Id
    tracking_number = "".join(random.choice("0123456789") for _ in range(22))
    track_body = {"capture_id": capture_id, "tracking_number": tracking_number,
                  "carrier": "USPS", "notify_payer": False}
    track_rid = rid()
    s, b, d, ms = call("POST", f"/v2/checkout/orders/{order_id}/track", token, track_body, track_rid)
    trackers = []
    for pu in (b.get("purchase_units") or []):
        trackers += (pu.get("shipping") or {}).get("trackers") or []
    tracker_id = trackers[0].get("id") if trackers else None
    record("8b. add tracking", s, b, d, ms, tracker_id=tracker_id,
           tracker_status=trackers[0].get("status") if trackers else None)
    s, b, d, ms = call("POST", f"/v2/checkout/orders/{order_id}/track", token, track_body, track_rid)
    record("8c. add tracking REPLAY (same Request-Id)", s, b, d, ms)

    # 8d. read back
    s, b, d, ms = call("GET", f"/v2/checkout/orders/{order_id}", token)
    count = sum(len((pu.get("shipping") or {}).get("trackers") or []) for pu in (b.get("purchase_units") or []))
    record("8d. order read-back", s, b, d, ms, order_status=b.get("status"), tracker_count=count)

    # 8e/8f. partial refund, then replay with the same Request-Id
    refund_rid = rid()
    refund_body = {"amount": money("10.00"), "note_to_payer": "AgentGuard spike partial refund"}
    s, b, d, ms = call("POST", f"/v2/payments/captures/{capture_id}/refund", token, refund_body, refund_rid)
    refund1 = b.get("id")
    record("8e. partial refund $10", s, b, d, ms, refund_id=refund1, status=b.get("status"))
    s, b, d, ms = call("POST", f"/v2/payments/captures/{capture_id}/refund", token, refund_body, refund_rid)
    record("8f. partial refund REPLAY (same Request-Id)", s, b, d, ms, refund_id=b.get("id"),
           same_refund=(b.get("id") == refund1) if b.get("id") else None)

    # 8g. over-refund must be refused
    s, b, d, ms = call("POST", f"/v2/payments/captures/{capture_id}/refund", token,
                       {"amount": money("35.00")}, rid())
    record("8g. over-refund $35 (only $30 left)", s, b, d, ms, refund_id=b.get("id"), status=b.get("status"))

    # 8h/8i. refund the rest, read the capture back
    s, b, d, ms = call("POST", f"/v2/payments/captures/{capture_id}/refund", token,
                       {"amount": money("30.00")}, rid())
    record("8h. refund remaining $30", s, b, d, ms, refund_id=b.get("id"), status=b.get("status"))
    s, b, d, ms = call("GET", f"/v2/payments/captures/{capture_id}", token)
    record("8i. capture read-back", s, b, d, ms, capture_status=b.get("status"))

    # 8j. cancel tracker
    if tracker_id:
        s, b, d, ms = call("PATCH", f"/v2/checkout/orders/{order_id}/trackers/{tracker_id}", token,
                           [{"op": "replace", "path": "/status", "value": "CANCELLED"}], rid())
        record("8j. cancel tracker", s, b, d, ms)


def main():
    token = get_token()
    if token:
        t9_honour_period(token)
        t8_refund_and_tracking(token)
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / time.strftime("%Y-%m-%d_%H%M_spike_v2_results.json")
    out.write_text(json.dumps({"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": RESULTS}, indent=2))
    print(f"\nSaved redacted results to {out}")


if __name__ == "__main__":
    main()
