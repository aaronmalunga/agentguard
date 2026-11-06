"""Live PayPal SANDBOX smoke test for the gateway (needs sandbox keys in .env; refuses anything but sandbox).

Run from the repo root:  uv run python scripts/smoke_gateway.py
Proves through the product code (not the spike): authorise -> capture, idempotent capture replay,
authorise -> void, a decline (HTTP 201 + DENIED), and Vault save -> charge with no buyer present.
Prints and saves ids, statuses, HTTP codes, PayPal debug ids and latency only. Never secrets.
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from agentguard.config import load_settings
from agentguard.paypal import PayPalError, PayPalGateway, vaulted_card
from agentguard.paypal.testing import sandbox_test_card

ROWS = []


def rid():
    return str(uuid.uuid4())


def row(step, expected_ok, **fields):
    ROWS.append({"step": step, "as_expected": bool(expected_ok), **fields})
    print(f"[{'OK  ' if expected_ok else 'FAIL'}] {step:<40} " + "  ".join(f"{k}={v}" for k, v in fields.items()))


def main():
    try:
        steps()
    except Exception as err:  # noqa: BLE001 -- record and still save, so a failure is evidence too
        row("STOPPED EARLY", False, error=type(err).__name__, detail=str(err)[:200],
            debug_id=getattr(err, "debug_id", None), http=getattr(err, "http_status", None))
    return save()


def steps():
    gw = PayPalGateway(load_settings())

    a = gw.authorize(amount="24.99", currency="USD", payment_source=sandbox_test_card(), request_id=rid(),
                     reference_id="smoke-approve")
    row("authorise (approve path)", a.authorized, http=a.http_status, status=a.status, ms=a.latency_ms)
    key = rid()
    c1 = gw.capture(a.authorization_id, request_id=key)
    row("capture", c1.succeeded, http=c1.http_status, status=c1.status, ms=c1.latency_ms)
    c2 = gw.capture(a.authorization_id, request_id=key)
    row("capture replay, same key", c2.capture_id == c1.capture_id, same_capture=c2.capture_id == c1.capture_id,
        http=c2.http_status, ms=c2.latency_ms)
    try:
        gw.capture(a.authorization_id, request_id=rid())
        row("capture again, new key -> refused", False)
    except PayPalError as e:
        row("capture again, new key -> refused", e.http_status == 422, http=e.http_status, issue=e.issue)

    b = gw.authorize(amount="149.00", currency="USD", payment_source=sandbox_test_card(), request_id=rid(),
                     reference_id="smoke-hold")
    row("authorise (hold path)", b.authorized, http=b.http_status, status=b.status, ms=b.latency_ms)
    v = gw.void(b.authorization_id, request_id=rid())
    row("void", v.succeeded, http=v.http_status, status=v.status, ms=v.latency_ms)

    d = gw.authorize(amount="9.99", currency="USD", payment_source=sandbox_test_card(name="CCREJECT-REFUSED"),
                     request_id=rid(), reference_id="smoke-decline")
    row("decline: HTTP 201 but not authorised", d.http_status == 201 and not d.authorized,
        http=d.http_status, status=d.status, ms=d.latency_ms)

    s = gw.authorize(amount="1.00", currency="USD", payment_source=sandbox_test_card(save=True),
                     request_id=rid(), reference_id="smoke-vault")
    row("vault on success", bool(s.vault_id), vault_id_present=bool(s.vault_id), ms=s.latency_ms)
    if s.authorized:
        gw.void(s.authorization_id, request_id=rid())
    if s.vault_id:
        g = gw.authorize(amount="12.50", currency="USD", payment_source=vaulted_card(s.vault_id),
                         request_id=rid(), reference_id="smoke-agent")
        row("agent charge via vault, no buyer", g.authorized, http=g.http_status, status=g.status,
            ms=g.latency_ms)
        if g.authorized:
            gw.void(g.authorization_id, request_id=rid())



def save():
    ok = sum(r["as_expected"] for r in ROWS)
    print(f"\n{ok}/{len(ROWS)} steps as expected")
    out = Path(__file__).resolve().parents[1] / "spike" / "results"
    out.mkdir(parents=True, exist_ok=True)
    name = out / f"{datetime.now():%Y-%m-%d_%H%M}_gateway_smoke.json"
    name.write_text(json.dumps({"ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                                "via": "agentguard.paypal.PayPalGateway (paypal-server-sdk)",
                                "results": ROWS}, indent=2), encoding="utf-8")
    print("saved", name.name)
    return 0 if ok == len(ROWS) else 1


if __name__ == "__main__":
    sys.exit(main())
