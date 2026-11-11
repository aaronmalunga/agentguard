"""Channel3 client: an independent market price for each cart line (sponsor integration, 9 Nov).

Why: the shop sets its own price, and the agent may be shown an inflated one. Channel3 is a universal product catalogue
with offers from many retailers, so the median in-stock price across those retailers is a neutral "usual price".
Rules (SPONSOR_STRATEGY.md, Ignacio's lens):
- Soft signal only. It feeds the existing price rule (more than 20% above the usual price -> hold). It never blocks and
  never approves; the merchant's catalogue stays the source of truth for the cart (decision D3).
- Fail safe and fast: any error or a 2.5 s timeout -> no market price; the catalogue's stored reference is used and
  labelled as such. A decision never waits on Channel3 for long.
- Decision-time calls use GET /v1/products/{id}, which Channel3 does not charge credits for. Prices are cached for
  15 minutes only (Channel3's guidance: don't cache prices for hours).
- The key lives in CHANNEL3_API_KEY (env var only). It is never logged or returned.

Product identity (11 Nov): the same free product lookup also returns the product's real title and brands. The shop's
listing (title, brand) is compared with that independent record; if they describe different products, the buyer is
asked first ("is this what you meant?"). Same soft-signal rules: it can only ask, never block or approve, and if
Channel3 doesn't answer no identity claim is made either way. Limitation: it checks the listing against the product
the shop links it to; it can't see what is actually in the box.
"""

import os
import re
import statistics
import threading
import time
from dataclasses import dataclass

import requests

BASE = "https://api.trychannel3.com"
TIMEOUT_S = 2.5
CACHE_S = 15 * 60


@dataclass(frozen=True)
class MarketPrice:
    product_id: str
    reference_cents: int          # median of in-stock USD offers
    low_cents: int
    high_cents: int
    offers: int                   # how many in-stock retailer offers the median is over
    domains: tuple[str, ...]
    latency_ms: int
    from_cache: bool = False
    source: str = "Channel3"
    title: str = ""                         # Channel3's own record of the product (identity check)
    brands: tuple[str, ...] = ()


class Channel3:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None,
                 clock=time.monotonic):
        self.key = api_key if api_key is not None else os.environ.get("CHANNEL3_API_KEY", "")
        self.http = session or requests.Session()
        self.clock = clock
        self._cache: dict[str, tuple[float, MarketPrice]] = {}
        self._lock = threading.Lock()
        self.errors = 0

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _call(self, method: str, path: str, **kw) -> dict:
        r = self.http.request(method, BASE + path, headers={"x-api-key": self.key, "Content-Type": "application/json"},
                              timeout=TIMEOUT_S, **kw)
        r.raise_for_status()
        return r.json()

    # -- catalogue building (costs credits; used by scripts/channel3_catalogue.py, not at decision time)
    def search(self, query: str, limit: int = 10, max_price: float | None = None) -> list[dict]:
        body = {"query": query, "limit": limit, "config": {"country": "US", "currency": "USD"}}
        if max_price:
            body["filters"] = {"price": {"max_price": max_price}}
        return self._call("POST", "/v1/search", json=body).get("products", [])

    def product(self, product_id: str) -> dict:
        return self._call("GET", f"/v1/products/{product_id}", params={"country": "US", "currency": "USD"})

    # -- decision time (free endpoint, cached, fail-safe)
    def market_price(self, product_id: str, exclude_domains: tuple[str, ...] = ()) -> MarketPrice | None:
        if not self.enabled or not product_id:
            return None
        now = self.clock()
        with self._lock:
            hit = self._cache.get(product_id)
            if hit and now - hit[0] < CACHE_S:
                return MarketPrice(**{**hit[1].__dict__, "from_cache": True})
        t0 = time.perf_counter()
        try:
            p = self.product(product_id)
        except (requests.RequestException, ValueError):
            self.errors += 1
            return None
        mp = summarise(p, exclude_domains, round((time.perf_counter() - t0) * 1000))
        if mp:
            with self._lock:
                self._cache[product_id] = (now, mp)
        return mp


def summarise(product: dict, exclude_domains: tuple[str, ...] = (), latency_ms: int = 0) -> MarketPrice | None:
    """Median of in-stock, new, USD offers. None when there is nothing to compare against."""
    prices, domains = [], []
    for o in product.get("offers") or []:
        pr = o.get("price") or {}
        if o.get("availability", "InStock") != "InStock" or pr.get("currency", "USD") != "USD":
            continue
        if o.get("condition") == "used" or o.get("domain") in exclude_domains or not pr.get("price"):
            continue
        prices.append(round(float(pr["price"]) * 100))
        domains.append(o.get("domain", ""))
    if not prices:
        return None
    return MarketPrice(product_id=product.get("id", ""), reference_cents=int(statistics.median(prices)),
                       low_cents=min(prices), high_cents=max(prices), offers=len(prices),
                       domains=tuple(sorted(set(domains)))[:8], latency_ms=latency_ms,
                       title=str(product.get("title") or "")[:200],
                       brands=tuple(str(b.get("name", "")) for b in (product.get("brands") or [])
                                    if isinstance(b, dict) and b.get("name"))[:5])


_FILLER = {"the", "and", "with", "for", "new", "a", "an", "of", "in", "by", "to", "pair", "set", "edition"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _codes(words: list[str]) -> set[str]:
    """Model codes: words with both letters and digits, or 3+ digits (e.g. 235bt, x900, 1000)."""
    return {w for w in words if (re.search(r"\d", w) and re.search(r"[a-z]", w)) or (w.isdigit() and len(w) >= 3)}


def _same_brand(shop_brand: str, real: tuple[str, ...]) -> bool:
    s = " ".join(_words(shop_brand))
    return any(s and (s == r or s in r or r in s) for r in (" ".join(_words(b)) for b in real) if r)


def compare_listing(shop_title: str, shop_brand: str | None, real_title: str, real_brands: tuple[str, ...]) -> str | None:
    """None when the shop's listing describes the same product as Channel3's record (or there is nothing to compare);
    otherwise a short plain-English reason ("brand", "model" or "name" differs)."""
    if not real_title:
        return None
    if shop_brand and real_brands and not _same_brand(shop_brand, real_brands):
        return "brand"
    shop, real = _words(shop_title), _words(real_title + " " + " ".join(real_brands))
    real_set = set(real) | {w.rstrip("s") for w in real}
    missing_codes = _codes(shop) - real_set
    if missing_codes:
        return "model"
    key = [w for w in shop if len(w) >= 3 and w not in _FILLER]
    if key:
        shared = sum(1 for w in key if w in real_set or w.rstrip("s") in real_set)
        # the shop may cut a long title short, so we ask what share of the SHOP's words the real record contains
        if shared / len(key) < 0.5:
            return "name"
    return None
