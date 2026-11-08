"""Score the guard on the frozen catalogues (docs/evaluation-plan.md).

  python eval/run_eval.py                      # dev split, all configs (free to run as often as you like)
  python eval/run_eval.py --split heldout --reason "rules-only baseline, look #1"   # logged held-out look

Writes evidence/runs/<timestamp>_<split>.json (raw per-case decisions + metrics + git commit + dataset hashes)
and, for held-out, appends one line to evidence/heldout_looks.jsonl. Numbers in docs come only from these files.
"""

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentguard.guard.engine import evaluate
from agentguard.guard.request import PaymentRequest
from agentguard.mandate import Mandate
from agentguard.money import to_cents

CONFIGS = {"rules_only": ("rules",), "rules+detector": ("rules", "detector")}
AI_CONFIG = ("rules+detector+ai", ("rules", "detector", "ai"))


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def load(split: str):
    if split in ("v2", "v3"):   # test-only catalogues, never tuned on
        rows = [json.loads(x) for x in (ROOT / f"eval/attacks/{split}/test.jsonl").read_text(encoding="utf-8")
                .splitlines()]
        return [{**c, "catalogue": split} for c in rows]
    cases = []
    for version in ("v0", "v1"):
        for line in (ROOT / "eval" / "attacks" / version / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            c["catalogue"] = version
            cases.append(c)
    return cases


def run_case(case, layers, registry, llm=None):
    m = Mandate.from_catalogue(case["mandate"])
    req = PaymentRequest.model_validate(case["request"])
    now = datetime.fromisoformat(case["now"])
    t0 = time.perf_counter()
    d = evaluate(req, m, now=now, registry=registry, spent_cents=to_cents(case["mandate"]["spent_so_far"]),
                 page_text=case["context"]["page_text"], layers=layers, llm=llm)
    return d, (time.perf_counter() - t0) * 1000


def metrics(rows, subset=None):
    rows = [r for r in rows if subset is None or subset(r)]
    att = [r for r in rows if r["is_attack"]]
    ben = [r for r in rows if not r["is_attack"]]
    blk = [r for r in rows if r["expected"] == "block"]
    caught = sum(r["got"] in ("ask", "block") for r in att)
    fb = sum(r["got"] == "block" for r in ben)
    su = sum(r["got"] == "ask" for r in ben)
    out = {"cases": len(rows), "attacks": len(att), "benign": len(ben),
           "catch_rate": round(caught / len(att), 4) if att else None, "catch_ci95": wilson(caught, len(att)),
           "caught": caught,
           "severe_misses": sum(r["got"] == "approve" for r in blk),
           "block_recall": round(sum(r["got"] == "block" for r in blk) / len(blk), 4) if blk else None,
           "false_block_rate": round(fb / len(ben), 4) if ben else None, "false_blocks": fb,
           "false_block_ci95": wilson(fb, len(ben)),
           "step_up_rate": round(su / len(ben), 4) if ben else None, "step_ups": su,
           "exact_match": round(sum(r["got"] == r["expected"] for r in rows) / len(rows), 4) if rows else None}
    conf = {}
    for r in rows:
        conf.setdefault(r["expected"], {}).setdefault(r["got"], 0)
        conf[r["expected"]][r["got"]] += 1
    out["confusion"] = conf
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "heldout", "v2", "v3"], default="dev")
    ap.add_argument("--reason", default="")
    ap.add_argument("--ai", action="store_true", help="add the LLM layer (Gemini; answers cached in evidence/)")
    ap.add_argument("--replay", action="store_true", help="AI answers from the cache only (no key, no calls)")
    ap.add_argument("--min-interval", type=float, default=4.5, help="seconds between fresh AI calls (free tier)")
    args = ap.parse_args()
    if args.split in ("heldout", "v2", "v3") and not args.reason:
        sys.exit("Held-out runs are logged looks. Give --reason.")
    registry = json.loads((ROOT / "eval" / "attacks" / "v0" / "merchants.json").read_text(encoding="utf-8"))
    cases = load(args.split)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=False, cwd=ROOT, capture_output=True,
                            text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "src"], check=False, cwd=ROOT, capture_output=True,
                                text=True).stdout.strip())
    hashes = {v: {f: json.loads((ROOT / "eval/attacks" / v / "MANIFEST.json").read_text())["files"][f]["sha256"]
                  for f in ("dev.jsonl", "heldout.jsonl")} for v in ("v0", "v1")}
    result = {"run_at": datetime.now(UTC).isoformat(timespec="seconds"), "split": args.split,
              "reason": args.reason, "git_commit": commit, "src_dirty": dirty, "dataset_sha256": hashes,
              "command": " ".join(["python", "eval/run_eval.py", *sys.argv[1:]]), "synthetic_data": True,
              "configs": {}}
    for v in ("v2", "v3"):
        if (ROOT / f"eval/attacks/{v}/MANIFEST.json").exists():
            hashes[v] = json.loads((ROOT / f"eval/attacks/{v}/MANIFEST.json").read_text())["files"]["test.jsonl"]["sha256"]
    ai_dep = lambda r: r["catalogue"] in ("v2", "v3") and r["is_attack"] or (r["catalogue"] == "v0" and r["expected"] == "ask") or (r["catalogue"] == "v1" and r["is_attack"])
    configs, llm = dict(CONFIGS), None
    if args.ai or args.replay:
        from dotenv import load_dotenv

        from agentguard.ai.cache import CachedLLM
        from agentguard.ai.llm import GeminiLLM
        load_dotenv(ROOT.parent / ".env")
        load_dotenv(ROOT / ".env")
        inner = None if args.replay else GeminiLLM()
        llm = CachedLLM(ROOT / "evidence" / "ai_cache.jsonl", inner,
                        model=__import__("os").environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                        min_interval_s=args.min_interval)
        configs[AI_CONFIG[0]] = AI_CONFIG[1]
    for name, layers in configs.items():
        rows, lat = [], []
        for c in cases:
            d, ms = run_case(c, layers, registry, llm if "ai" in layers else None)
            lat.append(ms)
            rows.append({"id": c["id"], "catalogue": c["catalogue"], "family": c["family"],
                         "template": c["template"], "is_attack": c["is_attack"], "expected": c["expected_decision"],
                         "got": d.eval_label, "level": d.level, "codes": [f.code for f in d.findings]})
        lat.sort()
        fam = {}
        for r in rows:
            f = fam.setdefault(f"{r['catalogue']}:{r['family']}", {"n": 0, "caught_or_correct": 0})
            f["n"] += 1
            f["caught_or_correct"] += (r["got"] in ("ask", "block")) if r["is_attack"] else (r["got"] == "approve")
        result["configs"][name] = {
            "layers": list(layers), "all": metrics(rows), "v0": metrics(rows, lambda r: r["catalogue"] == "v0"),
            "v1": metrics(rows, lambda r: r["catalogue"] == "v1"), "ai_dependent_subset": metrics(rows, ai_dep),
            "per_family": fam,
            "latency_ms": {"p50": round(lat[len(lat) // 2], 3), "p95": round(lat[int(len(lat) * 0.95) - 1], 3),
                           "max": round(lat[-1], 3), "n": len(lat), "note": "guard in-process, no PayPal, no AI"},
            "cases": rows}
        if "ai" in layers:
            fresh = sorted(x["latency_ms"] for x in llm.fresh_calls)
            result["configs"][name]["ai"] = {
                "model": llm.model, "fresh_calls": len(fresh), "failures": llm.failures,
                "schema_valid_rate": round(len(fresh) / (len(fresh) + llm.failures), 4) if fresh or llm.failures
                else None,
                "latency_ms_p50": fresh[len(fresh) // 2] if fresh else None,
                "latency_ms_p95": fresh[max(int(len(fresh) * 0.95) - 1, 0)] if fresh else None,
                "input_tokens": sum(x["input_tokens"] or 0 for x in llm.fresh_calls),
                "output_tokens": sum(x["output_tokens"] or 0 for x in llm.fresh_calls),
                "failure_reasons": llm.failure_reasons,
                "note": "latency from fresh calls only; cached replays excluded"}
    out = ROOT / "evidence" / "runs" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{args.split}.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if args.split in ("heldout", "v2", "v3"):
        with (ROOT / "evidence" / "heldout_looks.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"run_at": result["run_at"], "commit": commit, "reason": args.reason,
                                 "file": out.name}) + "\n")
    for name, cfg in result["configs"].items():
        a, s = cfg["all"], cfg["ai_dependent_subset"]
        print(f"{name:15} catch {a['catch_rate']:.1%} {a['catch_ci95']}  severe {a['severe_misses']}  "
              f"falseblock {a['false_blocks']}/{a['benign']}  stepup {a['step_ups']}/{a['benign']}  "
              f"exact {a['exact_match']:.1%} | AI-dependent catch {s['catch_rate']:.1%} ({s['caught']}/{s['attacks']})"
              f" | p95 {cfg['latency_ms']['p95']} ms")
    print("saved", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
