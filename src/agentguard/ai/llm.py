"""Thin, provider-agnostic LLM wrapper: one call returns a schema-validated object plus what it cost.

Provider and model come from configuration (ADR-0006). Output is validated against a Pydantic schema; anything
that fails (timeout, quota, network, invalid JSON) raises AIUnavailable, and callers turn that into
"ask the buyer" (fail-safe). Every call records model id, latency and token counts for the evidence log.
"""

import os
import time
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
DEFAULT_MODEL = "gemini-3.5-flash-lite"   # 2.5-flash-lite is closed to new users (8 Nov); override with GEMINI_MODEL


class AIUnavailable(Exception):
    pass


@dataclass(frozen=True)
class CallInfo:
    provider: str
    model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None


class LLM(Protocol):
    def json(self, *, system: str, user: str, schema: type[T]) -> tuple[T, CallInfo]: ...


class GeminiLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None, timeout_ms: int = 15000):  # Gemini rejects deadlines under 10 s
        from google import genai
        from google.genai import types
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise AIUnavailable("GEMINI_API_KEY is not set")
        self._types = types
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=timeout_ms))

    def json(self, *, system: str, user: str, schema: type[T]) -> tuple[T, CallInfo]:
        t = self._types
        start = time.perf_counter()
        try:
            r = self._client.models.generate_content(
                model=self.model, contents=user,
                config=t.GenerateContentConfig(system_instruction=system, temperature=0, seed=7,
                                               response_mime_type="application/json",
                                               response_json_schema=schema.model_json_schema(),
                                               max_output_tokens=2048))
            obj = schema.model_validate_json(r.text or "")
        except ValidationError as e:
            raise AIUnavailable(f"model output failed the schema ({e.error_count()} errors)") from None
        except Exception as e:  # noqa: BLE001 -- any provider failure means "ask the buyer"
            raise AIUnavailable(f"{type(e).__name__}: {str(e)[:160]}") from None
        u = r.usage_metadata
        return obj, CallInfo("gemini", self.model, round((time.perf_counter() - start) * 1000),
                             getattr(u, "prompt_token_count", None), getattr(u, "candidates_token_count", None))
