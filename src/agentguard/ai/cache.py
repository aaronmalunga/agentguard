"""Record-and-replay wrapper around an LLM (evaluation and keyless CI).

Each distinct (model, system, user) is called once; the validated answer is stored in a JSONL file, so reruns cost
nothing and CI can replay real model answers without a key ("recorded fixtures", ADR-0006). Replayed calls are
marked from_cache and never counted as latency.
"""

import hashlib
import json
import time
from pathlib import Path

from agentguard.ai.llm import AIUnavailable, CallInfo


class CachedLLM:
    def __init__(self, path: Path, inner=None, model: str = "", min_interval_s: float = 0.0):
        self.path, self.inner, self.min_interval = path, inner, min_interval_s
        self.model = getattr(inner, "model", model)
        self.store: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                self.store[rec["key"]] = rec
        self._last = 0.0
        self.fresh_calls: list[dict] = []
        self.failures = 0
        self.failure_reasons: list[str] = []   # provider messages only, never the key

    def _key(self, system, user, schema):
        return hashlib.sha256(f"{self.model}|{schema.__name__}|{system}|{user}".encode()).hexdigest()

    def json(self, *, system, user, schema):
        k = self._key(system, user, schema)
        if k in self.store:
            rec = self.store[k]
            info = CallInfo(**{**rec["info"], "latency_ms": 0})
            return schema.model_validate(rec["output"]), info
        if self.inner is None:
            raise AIUnavailable("no recorded answer and no live model")
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            obj, info = self.inner.json(system=system, user=user, schema=schema)
        except AIUnavailable as e:
            self.failures += 1
            self.failure_reasons.append(str(e)[:120])
            raise
        rec = {"key": k, "schema": schema.__name__, "output": obj.model_dump(), "info": info.__dict__}
        self.store[k] = rec
        self.fresh_calls.append(info.__dict__)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return obj, info


class RecordedFirstLLM(CachedLLM):
    """Demo mode (decision D14, 8 Nov): the scripted demo scenarios replay REAL model answers recorded once
    (`scripts/record_demo_answers.py`); anything new goes to the live model. A replayed answer is labelled:
    provider "recorded <date>", and its latency is the latency measured when it was recorded, never 0 or invented.
    New live answers are NOT added to the file at runtime (the hosted demo's disk is not evidence)."""

    def json(self, *, system, user, schema):
        k = self._key(system, user, schema)
        if k in self.store:
            rec = self.store[k]
            info = CallInfo(**{**rec["info"], "provider": f"recorded {rec.get('recorded_at', '')}".strip()})
            return schema.model_validate(rec["output"]), info
        if self.inner is None:
            raise AIUnavailable("no recorded answer and no live model")
        return self.inner.json(system=system, user=user, schema=schema)
