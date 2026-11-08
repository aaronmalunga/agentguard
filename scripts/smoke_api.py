"""Live check of the WEB API against the real PayPal SANDBOX and the real AI model (Gemini).

Run from the repo root:  uv run python scripts/smoke_api.py
1. Saves PayPal's public sandbox test card in the PayPal vault once ($1.00 authorisation, then voided) unless
   AGENTGUARD_VAULT_ID is already set. Prints the vault id: put it in .env as AGENTGUARD_VAULT_ID for the hosted demo.
2. Runs the five demo scenarios through the same HTTP endpoints judges will use, then answers the hold
   (reject -> void) and checks a signed receipt and the audit chain.
Saves statuses, PayPal ids, AI model + latency. Never secrets.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")


def vault_once() -> str:
    from agentguard.config import load_settings
    from agentguard.paypal import PayPalGateway
    from agentguard.paypal.testing import sandbox_test_card
    gw = PayPalGateway(load_settings())
    run = datetime.now().strftime("%Y%m%d%H%M%S")
    a = gw.authorize(amount="1.00", currency="USD", payment_source=sandbox_test_card(save=True),
                     request_id=f"vault-{run}", reference_id=f"vault-{run}", description="AgentGuard vault setup")
    if a.authorization_id:
        gw.void(a.authorization_id, request_id=f"vault-{run}-void")
    if not a.vault_id:
        sys.exit(f"PayPal did not return a vault id (status {a.status}); cannot continue")
    return a.vault_id


def main():
    os.environ["AGENTGUARD_PAYPAL"] = "sandbox"
    made = not os.environ.get("AGENTGUARD_VAULT_ID")
    if made:
        os.environ["AGENTGUARD_VAULT_ID"] = vault_once()
    from agentguard.web.app import create_app
    c = TestClient(create_app(paypal_mode="sandbox", tokens={"agent": "smoke-a", "buyer": "smoke-b"}))
    B = {"Authorization": "Bearer smoke-b"}
    health = c.get("/healthz").json()
    print("health:", health)
    expected = {"normal": {"captured"}, "poisoned": {"blocked"}, "inflated": {"held"},
                "out_of_stock_swap": {"held", "awaiting_buyer"}, "agent_lies": {"awaiting_buyer"}}
    rows = []
    for sc, ok_set in expected.items():
        p = c.post("/api/demo/run", json={"scenario": sc}, headers=B).json()["payment"]
        ok = p["status"] in ok_set
        ai = p.get("ai") or {}
        rows.append({"scenario": sc, "expected": sorted(ok_set), "status": p["status"], "as_expected": ok,
                     "level": p["level"], "codes": [f["code"] for f in p["findings"]],
                     "paypal_order_id": p.get("paypal_order_id"), "paypal_status": p.get("paypal_status"),
                     "paypal_called": p["paypal_called"], "ai_model": ai.get("model"),
                     "ai_latency_ms": ai.get("latency_ms"), "payment_id": p["id"]})
        print(f"[{'OK  ' if ok else 'FAIL'}] {sc:<18} {p['status']:<15} PayPal: {p.get('paypal_status')}  "
              f"AI: {ai.get('model')} {ai.get('latency_ms')} ms  {[f['code'] for f in p['findings']]}")
    held = next((r for r in rows if r["scenario"] == "inflated"), None)
    if held and held["status"] == "held":
        v = c.post(f"/api/payments/{held['payment_id']}/reject", headers=B).json()
        ok = v["status"] == "voided"
        rows.append({"scenario": "inflated -> buyer rejects", "expected": ["voided"], "status": v["status"],
                     "as_expected": ok, "paypal_status": v.get("paypal_status"),
                     "paypal_order_id": v.get("paypal_order_id")})
        print(f"[{'OK  ' if ok else 'FAIL'}] buyer rejects hold   {v['status']:<15} PayPal: {v.get('paypal_status')}")
    rec = c.get(f"/api/payments/{rows[0]['payment_id']}/receipt", headers=B).json()
    rv = c.post("/api/receipts/verify", json=rec).json()
    av = c.get("/api/audit/verify").json()
    rows.append({"scenario": "receipt verifies", "as_expected": rv["valid"], "status": rv})
    rows.append({"scenario": "audit chain verifies", "as_expected": av["ok"], "status": av})
    print(f"[{'OK  ' if rv['valid'] else 'FAIL'}] receipt verifies      {rv['checks']}")
    print(f"[{'OK  ' if av['ok'] else 'FAIL'}] audit chain verifies  {av['checked']} entries")
    n = sum(bool(r["as_expected"]) for r in rows)
    print(f"\n{n}/{len(rows)} steps as expected")
    if made:
        print(f"\nAdd this line to your .env for the hosted demo:\nAGENTGUARD_VAULT_ID={os.environ['AGENTGUARD_VAULT_ID']}")
    out = ROOT / "spike" / "results" / f"{datetime.now():%Y-%m-%d_%H%M}_api_smoke.json"
    out.write_text(json.dumps({"ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                               "via": "agentguard.web.app (HTTP API) + PayPal sandbox + AI model",
                               "health": health, "results": rows}, indent=2, default=str), encoding="utf-8")
    print("saved", out.name)
    return 0 if n == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
