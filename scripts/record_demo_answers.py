"""Record the REAL AI answers for the scripted demo scenarios, once (decision D14).

Run from the repo root when the Gemini quota is available:  uv run python scripts/record_demo_answers.py
Writes src/agentguard/web/demo_ai_answers.jsonl (model output + model id + measured latency + date). The hosted demo
replays these for the five scripted scenarios, labelled "recorded <date>" on screen; anything new calls the model live.

Add one scenario without touching the others (11 Nov):  uv run python scripts/record_demo_answers.py --add mislabelled
(keeps every existing answer and its date; only the named scenarios call the model).
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")
OUT = ROOT / "src" / "agentguard" / "web" / "demo_ai_answers.jsonl"


def main():
    from agentguard.ai.cache import CachedLLM
    from agentguard.ai.llm import GeminiLLM
    from agentguard.web import demo
    from agentguard.web.app import create_app
    add = sys.argv[2:] if len(sys.argv) > 2 and sys.argv[1] == "--add" else []
    if OUT.exists() and not add:
        OUT.unlink()   # start clean: answers recorded for an older catalogue or wording would never match again
    rec = CachedLLM(OUT, inner=GeminiLLM(), min_interval_s=8)   # pace calls: free tier also limits per minute
    c = TestClient(create_app(paypal_mode="fake", llm=rec, tokens={"agent": "a", "buyer": "b"}, demo_mode=True))
    ok = 0
    names = add or list(demo.SCENARIOS)
    for sc in names:
        p = c.post("/api/demo/run", json={"scenario": sc}, headers={"Authorization": "Bearer b"}).json()["payment"]
        ai = p.get("ai") or {}
        good = "model" in ai
        ok += good
        when = "recorded earlier" if good and ai.get("latency_ms") == 0 else f"{ai.get('latency_ms')} ms"
        print(f"[{'OK  ' if good else 'FAIL'}] {sc:<18} {p['level']:<10} AI: {ai.get('model')} {when}")
    if rec.failures:
        print("failures:", rec.failure_reasons)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines()] if OUT.exists() else []
    OUT.write_text("".join(json.dumps({**r, "recorded_at": r.get("recorded_at", stamp)}, ensure_ascii=False) + "\n"
                           for r in lines), encoding="utf-8")
    print(f"\n{ok}/{len(names)} scenarios have a recorded AI answer -> {OUT.relative_to(ROOT)}")
    return 0 if ok == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
