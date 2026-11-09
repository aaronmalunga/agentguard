"""Build the demo shop's catalogue from REAL products in Channel3 (run once; uses a few search credits).

Run from the repo root:  uv run python scripts/channel3_catalogue.py
Writes src/agentguard/web/channel3_catalogue.json: real product titles, brands, images and Channel3 ids, plus the
market price (median of in-stock US offers) at the time of the snapshot. The demo shop (SoundMart) is still made up;
its prices are set from these market prices, except the "inflated" item, priced deliberately above the market.
Never prints the API key.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")
OUT = ROOT / "src" / "agentguard" / "web" / "channel3_catalogue.json"

# role -> (queries, min $, max $, words the title must NOT contain). Brand queries first: well-known products are sold
# by many retailers, so the market median rests on several shops, not one (review 9 Nov: "median of 1 shop").
ROLES = {
    "normal":       (["Sony wireless noise cancelling earbuds", "JBL noise cancelling wireless earbuds",
                      "Soundcore noise cancelling earbuds", "wireless noise cancelling earbuds"], 50, 140,
                     ("case", "tips", "wired", "refurb", "renewed")),
    "inflated":     (["JBL Tune wireless earbuds", "Skullcandy wireless earbuds", "Soundcore wireless earbuds",
                      "wireless earbuds bluetooth"], 30, 85, ("case", "tips", "wired", "refurb", "renewed")),
    "out_of_stock": (["Jabra wireless earbuds", "Beats wireless earbuds", "Bose wireless earbuds",
                      "noise cancelling earbuds"], 60, 145, ("case", "tips", "wired", "refurb", "renewed")),
    "swap_target":  (["Apple EarPods wired", "Sony wired earphones", "JBL wired earphones",
                      "wired earphones with microphone"], 12, 80, ("wireless", "bluetooth", "case", "refurb")),
    "accessory":    (["earbuds replacement ear tips", "AirPods Pro case cover", "earbuds charging case"], 8, 60,
                     ("earphones with mic", "refurb")),
}
MIN_SHOPS = 3


def main():
    from agentguard.market.channel3 import Channel3, summarise
    c3 = Channel3()
    if not c3.enabled:
        sys.exit("CHANNEL3_API_KEY is not set in .env")
    picked, used = [], set()
    for role, (queries, lo, hi, avoid) in ROLES.items():
        best = None   # most shops wins; a product sold by MIN_SHOPS+ shops ends the search early
        for q in queries:
            for p in c3.search(q, limit=20, max_price=hi):
                title = p.get("title", "")
                if p.get("id") in used or any(w in title.lower() for w in avoid):
                    continue
                mp = summarise(p)
                if mp and lo * 100 <= mp.reference_cents <= hi * 100 and (best is None or mp.offers > best[1].offers):
                    best = (p, mp)
            if best and best[1].offers >= MIN_SHOPS:
                break
        found = best
        if not found:
            print(f"[FAIL] {role:<13} nothing suitable")
            continue
        p, mp = found
        used.add(p["id"])
        img = next((i.get("cleaned_url") or i.get("url") for i in (p.get("images") or []) if i.get("is_main_image")),
                   None) or next((i.get("cleaned_url") or i.get("url") for i in (p.get("images") or [])), None)
        picked.append({"role": role, "channel3_id": p["id"], "title": p["title"][:90],
                       "brand": ", ".join(b["name"] for b in (p.get("brands") or []))[:40],
                       "image": img, "market_cents": mp.reference_cents, "market_offers": mp.offers,
                       "market_low_cents": mp.low_cents, "market_high_cents": mp.high_cents,
                       "market_domains": list(mp.domains)})
        flag = "OK  " if mp.offers >= MIN_SHOPS else "THIN"
        print(f"[{flag}] {role:<13} {p['title'][:60]:<60} market ${mp.reference_cents / 100:.2f} "
              f"({mp.offers} shops)")
    OUT.write_text(json.dumps({"source": "Channel3 product search (US, USD)",
                               "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
                               "products": picked}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{len(picked)}/{len(ROLES)} roles filled -> {OUT.relative_to(ROOT)}")
    return 0 if len(picked) == len(ROLES) else 1


if __name__ == "__main__":
    sys.exit(main())
