"""Channel3 market price: real products in the demo, live median as a soft signal, fail-safe fallback."""

import json

import requests
from fastapi.testclient import TestClient

from agentguard.market.channel3 import Channel3, MarketPrice, compare_listing, summarise
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
        r = next(p for p in SNAP["products"] if p["channel3_id"] == product_id)
        cents = r["market_cents"]
        return MarketPrice(product_id, cents, cents - 300, cents + 900, 6, ("a.com", "b.com"), 412,
                           title=r["title"], brands=(r["brand"],))


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


def test_thin_market_is_labelled(tmp_path, monkeypatch):
    class Thin(FakeMarket):
        def market_price(self, product_id, exclude_domains=()):
            mp = super().market_price(product_id)
            return MarketPrice(**{**mp.__dict__, "offers": 1})
    c = app_with(tmp_path, monkeypatch, Thin())
    p = c.post("/api/demo/run", json={"scenario": "inflated"}, headers=BUYER).json()["payment"]
    assert p["status"] == "held" and p["facts"]["items"][0]["usual_price_source"] == "Channel3, 1 shop only"


# ------------------------------------------------------------------ product identity (11 Nov): listing vs real product
def test_listing_that_matches_the_real_product_passes():
    assert compare_listing("Acme ANC Wireless Earbuds", "Acme", "Acme ANC Wireless Earbuds", ("Acme",)) is None
    # the shop keeps titles to 90 characters: a cut-off title still matches
    long = "Sony WF-C710N Active Noise Canceling True Wireless Bluetooth Earbuds with Charging Case and Mic"
    assert compare_listing(long[:60], "Sony", long, ("Sony",)) is None
    assert compare_listing("Tune 235BT earbuds", "JBL", "JBL Tune 235BT Wireless Earbud Headphones",
                           ("JBL", "Harman")) is None


def test_listing_that_names_another_brand_or_product_is_flagged():
    why = compare_listing("Aura Studio Pro ANC wireless earbuds", "Aura",
                          "JBL Tune 235BT Wireless Earbud Headphones", ("JBL",))
    assert why and "brand" in why
    why = compare_listing("Acme X900 ANC earbuds", "Acme", "Acme X100 Wired Earphones", ("Acme",))
    assert why and "model" in why
    assert compare_listing("Acme earbuds", "Acme", "", ()) is None          # nothing to compare: no claim either way


def test_mislabelled_listing_asks_the_buyer_and_names_both_products(tmp_path, monkeypatch):
    c = app_with(tmp_path, monkeypatch, FakeMarket())
    names = {s["id"] if isinstance(s, dict) and "id" in s else s for s in c.get("/api/demo/scenarios").json()}
    assert any("mislabelled" in str(n) for n in names)
    p = c.post("/api/demo/run", json={"scenario": "mislabelled"}, headers=BUYER).json()["payment"]
    f = next(f for f in p["findings"] if f["code"] == "listing_mismatch")
    assert f["level"] == "ask_first" and "Bolt Wireless Earbuds" in f["reason"] and "Aura" in f["reason"]
    assert p["status"] == "awaiting_buyer" and not p["paypal_called"]
    chk = next(t for t in p["trace"] if t["layer"] == "market")["checks"][0]
    assert chk["listing_match"] is False and chk["c3_title"] == "Bolt Wireless Earbuds"
    assert not any(f["code"] == "price_above_reference" for f in p["findings"])   # price alone looks normal


def test_honest_listings_are_not_flagged(tmp_path, monkeypatch):
    c = app_with(tmp_path, monkeypatch, FakeMarket())
    for sc in ("normal", "inflated", "agent_lies"):
        p = c.post("/api/demo/run", json={"scenario": sc}, headers=BUYER).json()["payment"]
        assert not any(f["code"] == "listing_mismatch" for f in p["findings"]), sc
        assert next(t for t in p["trace"] if t["layer"] == "market")["checks"][0]["listing_match"] is True


def test_identity_check_fails_open_to_the_other_checks_when_channel3_is_down(tmp_path, monkeypatch):
    # Channel3 down: no identity claim is made either way (soft signal, like the price); the other layers still run
    c = app_with(tmp_path, monkeypatch, FakeMarket(down=True))
    p = c.post("/api/demo/run", json={"scenario": "mislabelled"}, headers=BUYER).json()["payment"]
    assert not any(f["code"] == "listing_mismatch" for f in p["findings"])
    assert next(t for t in p["trace"] if t["layer"] == "market")["checks"][0]["live"] is False


def test_summarise_keeps_the_real_title_and_brands():
    mp = summarise({"id": "x", "title": "JBL Tune 235BT", "brands": [{"name": "JBL"}], "offers": [
        {"domain": "a.com", "price": {"price": 40, "currency": "USD"}, "availability": "InStock"}]})
    assert mp.title == "JBL Tune 235BT" and mp.brands == ("JBL",)


def test_without_a_gemini_key_the_scripted_scenarios_still_replay_recorded_answers(monkeypatch):
    # 11 Nov: found while checking the "remove the key" option. Recordings are keyed by model; with no key the app
    # used NoAI's name, so nothing matched and every button fell back to "ask". Uses the real catalogue + recordings.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("CHANNEL3_API_KEY", raising=False)
    c = TestClient(create_app(paypal_mode="fake", tokens={"agent": "a", "buyer": "b"}, demo_mode=True))
    for sc in ("normal", "poisoned", "inflated", "out_of_stock_swap", "agent_lies"):
        p = c.post("/api/demo/run", json={"scenario": sc}, headers={"Authorization": "Bearer b"}).json()["payment"]
        assert (p.get("ai") or {}).get("provider", "").startswith("recorded"), sc
    assert c.post("/api/demo/run", json={"scenario": "normal"},
                  headers={"Authorization": "Bearer b"}).json()["payment"]["status"] == "captured"


def test_healthz_says_whether_a_live_model_answers(monkeypatch):
    # 11 Nov, option C (no paid key): the header must not imply a live model when only saved answers replay.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("CHANNEL3_API_KEY", raising=False)
    no_key = TestClient(create_app(paypal_mode="fake", tokens={"agent": "a", "buyer": "b"}, demo_mode=True))
    assert no_key.get("/healthz").json()["live_ai"] is False
    off = TestClient(create_app(paypal_mode="fake", ai="off", tokens={"agent": "a", "buyer": "b"}, demo_mode=True))
    assert off.get("/healthz").json()["live_ai"] is False
