"""Channel3 market price: real products in the demo, live median as a soft signal, fail-safe fallback."""

import json

import requests
from fastapi.testclient import TestClient

from agentguard.market.channel3 import Channel3, MarketPrice, summarise
from agentguard.web import demo
from agentguard.web.app import create_app
from tests.unit.test_web import BUYER, NOW, FakeLLM

SNAP = {"source": "test", "retrieved_at": "2026-11-09T09:30:00+00:00", "products": [
    {"role": r, "channel3_id": f"c3_{r}", "title": t, "brand": "B", "image": None, "market_cents": c,
     "market_offers": 4, "market_low_cents": c - 500, "market_high_cents": c + 500, "market_domains": ["a.com"]}
    for r, t, c in (("normal", "Acme ANC Wireless Earbuds", 7999), ("inflated", "Bolt Wireless Earbuds", 4999),
                    ("out_of_stock", "Crest Noise Cancelling Earbuds", 12999),
                    ("swap_target", "Dyna Wired Earphones with Mic", 2999),
                    ("accessory", "Echo Earbuds Charging Case", 1999))]}


class FakeMarket:
    enabled = True

    def __init__(self, down=False):
        self.down, self.calls = down, []

    def market_price(self, product_id, exclude_domains=()):
        self.calls.append(product_id)
        if self.down:
            return None
        cents = next(p["market_cents"] for p in SNAP["products"] if p["channel3_id"] == product_id)
        return MarketPrice(product_id, cents, cents - 300, cents + 900, 6, ("a.com", "b.com"), 412)


def app_with(tmp_path, monkeypatch, market):
    f = tmp_path / "snap.json"
    f.write_text(json.dumps(SNAP))
    monkeypatch.setattr(demo, "SNAPSHOT", f)
    return TestClient(create_app(paypal_mode="fake", llm=FakeLLM(), clock=lambda: NOW,
                                 tokens={"agent": "a-tok", "buyer": "b-tok"}, demo_mode=True, market=market))


def test_demo_uses_real_products_and_live_market_price(tmp_path, monkeypatch):
    m = FakeMarket()
    c = app_with(tmp_path, monkeypatch, m)
    cat = c.get("/api/catalogue").json()
    assert cat["source"].startswith("Channel3") and cat["products"][0]["title"] == "Acme ANC Wireless Earbuds"
    p = c.post("/api/demo/run", json={"scenario": "inflated"}, headers=BUYER).json()["payment"]
    assert p["status"] == "held" and p["amount_cents"] == 8299            # 1.65 x $49.99, ending .99
    reason = next(f["reason"] for f in p["findings"] if f["code"] == "price_above_reference")
    assert "Channel3, median of 6 shops" in reason
    step = next(t for t in p["trace"] if t["layer"] == "market")
    assert step["checks"][0]["live"] is True and step["checks"][0]["offers"] == 6
    assert p["facts"]["items"][0]["usual_price_source"] == "Channel3, median of 6 shops"


def test_market_down_falls_back_to_snapshot_and_never_blocks(tmp_path, monkeypatch):
    c = app_with(tmp_path, monkeypatch, FakeMarket(down=True))
    p = c.post("/api/demo/run", json={"scenario": "normal"}, headers=BUYER).json()["payment"]
    assert p["status"] == "captured"
    assert p["facts"]["items"][0]["usual_price_source"] == "Channel3 snapshot 2026-11-09"
    assert next(t for t in p["trace"] if t["layer"] == "market")["checks"][0]["live"] is False


def test_summarise_uses_in_stock_new_usd_offers_only():
    p = {"id": "x", "offers": [
        {"domain": "a.com", "price": {"price": 50, "currency": "USD"}, "availability": "InStock"},
        {"domain": "b.com", "price": {"price": 70, "currency": "USD"}, "availability": "InStock"},
        {"domain": "c.com", "price": {"price": 10, "currency": "USD"}, "availability": "OutOfStock"},
        {"domain": "d.com", "price": {"price": 20, "currency": "EUR"}, "availability": "InStock"},
        {"domain": "e.com", "price": {"price": 5, "currency": "USD"}, "availability": "InStock", "condition": "used"}]}
    mp = summarise(p)
    assert (mp.reference_cents, mp.low_cents, mp.high_cents, mp.offers) == (6000, 5000, 7000, 2)
    assert summarise({"id": "y", "offers": []}) is None


def test_client_fails_safe_and_caches(monkeypatch):
    class Boom(requests.Session):
        def request(self, *a, **k):
            raise requests.ConnectTimeout("slow")
    c3 = Channel3(api_key="k", session=Boom())
    assert c3.market_price("p1") is None and c3.errors == 1
    t = [0.0]
    ok = Channel3(api_key="k", clock=lambda: t[0])
    monkeypatch.setattr(ok, "product", lambda pid: {"id": pid, "offers": [
        {"domain": "a.com", "price": {"price": 40, "currency": "USD"}, "availability": "InStock"}]})
    assert ok.market_price("p1").from_cache is False
    assert ok.market_price("p1").from_cache is True
    t[0] = 16 * 60
    assert ok.market_price("p1").from_cache is False
    assert Channel3(api_key="").market_price("p1") is None
