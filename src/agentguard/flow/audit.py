"""Tamper-evident decision log: every entry carries the hash of the one before it (a hash chain).

Change, delete or reorder any past entry and every hash after it stops matching, so `verify()` points at the first
broken entry. This proves the log wasn't edited after the fact; it does not stop someone who controls the database
from rewriting the WHOLE chain. That's why each signed receipt also carries the chain head at the time it was
issued (a second, independent copy), and why the roadmap anchors the head in write-once storage (S3 Object Lock).
"""

import hashlib
import json

GENESIS = "0" * 64


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def link(prev_hash: str, rec: dict) -> str:
    body = canonical({k: rec[k] for k in ("seq", "at", "kind", "payment_id", "data_json")})
    return hashlib.sha256(f"{prev_hash}\n{body}".encode()).hexdigest()


def verify(entries: list[dict]) -> dict:
    """Walk the chain from the start. Returns ok, entries checked, and the first bad seq (if any)."""
    prev = GENESIS
    for i, e in enumerate(entries, start=1):
        if e["seq"] != i or e["prev_hash"] != prev or link(prev, e) != e["hash"]:
            return {"ok": False, "checked": i - 1, "first_bad_seq": e["seq"],
                    "reason": "entry changed, missing or out of order"}
        prev = e["hash"]
    return {"ok": True, "checked": len(entries), "first_bad_seq": None, "head": prev}
