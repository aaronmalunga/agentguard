"""Every demo scenario in every setting we might ship in (11 Nov).

Why: the keyless-replay bug lived in a setting no test ran (no Gemini key). Each setting below is one a judge could
meet on the live site: key on (FakeLLM stands in), key removed (recorded answers only), Channel3 up / down / off,
AI switched off, shadow mode. Checks are the promises made in the README, not exact wording.
"""

import json

import pytest
from fastapi.testclient import TestClient

from agentguard.market.channel3 import MarketPrice
from agentguard.web import demo
from agentguard.web.app import create_app
from tests.unit.test_web import FakeLLM

SNAP = json.loads(demo.SNAPSHOT.read_text(encoding="utf-8"))
BY_ID = {p["channel3_id"]: p for p in SNAP["products"]}
B = {"Authorization": "Bearer b"}
SCENARIOS = ("normal", "poisoned", "inflated", "out_of_stock_swap", "agent_lies", "mislabelled")
PAID = {"captured", "partially_refunded", "refunded"}


class SnapMarket:
    """Channel3 answering with the snapshot's data (real products, real titles and brands)."""
    enabled = True

    def __init__(self, down=False):
        self.down = down

    def market_price(self, pid, exclude_domains=()):
        if self.down:
            return None
        r = BY_ID[pid]
        return MarketPrice(pid, r["market_cents"], r["market_low_cents"], r["market_high_cents"], r["market_offers"],
                           tuple(r["market_domains"]), 5, title=r["title"],
                           brands=tuple(b.strip() for b in r["brand"].split(",") if b.strip()))


SETTINGS = {
    "key_on_channel3_up": {"llm": FakeLLM(), "market": SnapMarket()},
    "key_removed_channel3_up": {"market": SnapMarket()},
    "key_removed_channel3_down": {"market": SnapMarket(down=True)},
    "key_removed_channel3_off": {"market": None},
    "ai_off_channel3_up": {"ai": "off", "market": SnapMarket()},
}


def run_all(monkeypatch, shadow=False, **kw):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    c = TestClient(create_app(paypal_mode="fake", tokens={"agent": "a", "buyer": "b"}, demo_mode=True, **kw))
    if shadow:
        cur = c.get("/api/mandates", headers=B).json()
        cur = (cur[0] if isinstance(cur, list) else next(iter(cur.values())))
        cur = cur.get("mandate", cur)
        assert c.post("/api/mandates", json={"mandate": {**cur, "version": cur["version"] + 1, "mode": "shadow"}},
                      headers=B).status_code == 201
    out = {}
    for sc in SCENARIOS:
        r = c.post("/api/demo/run", json={"scenario": sc}, headers=B)
        assert r.status_code == 200, (sc, r.text[:200])
        out[sc] = r.json()["payment"]
    return c, out


@pytest.mark.parametrize("setting", SETTINGS)
def test_every_scenario_keeps_its_promises_in_every_setting(monkeypatch, setting):
    _, p = run_all(monkeypatch, **SETTINGS[setting])
    assert p["normal"]["status"] == "captured", setting                      # a good purchase always goes through
    for sc in ("poisoned", "agent_lies", "inflated"):                         # rules, detector and price catch these
        assert p[sc]["status"] not in PAID, (setting, sc)                     # in every setting, AI or not
    if setting.startswith("key_removed"):
        # the out-of-stock swap is caught by the AI layer only (an in-limit attack): judged here with the REAL recorded
        # answers. With the stand-in AI (key_on) or AI off it can go through; that is the documented rules-only gap.
        assert p["out_of_stock_swap"]["status"] not in PAID, setting
    for sc in ("poisoned", "agent_lies"):
        assert not p[sc]["paypal_called"], (setting, sc)                      # stopped before PayPal
    if "channel3_up" in setting:
        assert p["mislabelled"]["status"] not in PAID and \
            any(f["code"] == "listing_mismatch" for f in p["mislabelled"]["findings"]), setting
    if setting.startswith("key_removed"):                                     # recorded answers still replay
        for sc in SCENARIOS:
            assert (p[sc].get("ai") or {}).get("provider", "").startswith("recorded"), (setting, sc)


def test_shadow_mode_in_the_shipped_setting(monkeypatch):
    c, p = run_all(monkeypatch, shadow=True, market=SnapMarket())
    for sc in SCENARIOS:
        assert (p[sc].get("shadow") or {}).get("mode") == "shadow", sc       # every decision records what would have happened
    assert p["normal"]["status"] == "captured"
    assert p["mislabelled"]["shadow"]["would_have"] == "ask_first"            # logged, not enforced: a judgement check
    r = c.get("/api/mandates/thandi-earbuds/shadow-report", headers=B).json()
    assert r["decided_in_shadow"] == len(SCENARIOS) and r["would_have_stopped"] >= 4
