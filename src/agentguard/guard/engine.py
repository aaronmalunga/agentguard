"""Guard entry point: rules first (base decision), then later layers that may only escalate.

Layers: "rules" (deterministic), "detector" (local, no AI call), "ai" (LLM intent check, ADR-0006).
The AI layer is skipped when the payment is already blocked (no point spending a call), and any AI failure
becomes "ask the buyer".
"""

import time
from dataclasses import asdict
from datetime import datetime

from agentguard.guard import detector, rules
from agentguard.guard.decision import Decision, Finding, combine, escalate
from agentguard.guard.request import PaymentRequest
from agentguard.mandate import Mandate

LAYERS = ("rules", "detector", "ai")


def evaluate(request: PaymentRequest, mandate: Mandate | None, *, now: datetime, registry: dict[str, str],
             spent_cents: int, page_text: str = "", layers: tuple[str, ...] = LAYERS, llm=None) -> Decision:
    trace: list[dict] = []

    def timed(name, fn):   # records how long each layer took and what it raised (shown in the decision trace)
        t0 = time.perf_counter()
        out = fn()
        found = out[0] if isinstance(out, tuple) else out
        trace.append({"layer": name, "ms": round((time.perf_counter() - t0) * 1000, 2),
                      "codes": [f.code for f in found]})
        return out

    decision = combine(timed("rules", lambda: rules.check(request, mandate, now=now, registry=registry,
                                                          spent_cents=spent_cents)),
                       verified_facts=rules.verified_facts(request, mandate, spent_cents),
                       agent_note=request.agent_note)
    if "detector" in layers:
        decision = escalate(decision, timed("detector", lambda: detector.scan(page_text)))
    if "ai" in layers and llm is not None and mandate is not None and decision.level == "block":
        trace.append({"layer": "ai", "ms": 0, "codes": [], "skipped": "already blocked by rules"})
    if "ai" in layers and llm is not None and mandate is not None and decision.level != "block":
        from agentguard.ai import intent
        found, info = timed("ai", lambda: intent.check(llm, request, mandate, page_text))
        codes = {f.code for f in decision.findings} | {f.code for f in found}
        page_steered = "hidden_instruction" in codes or "ai_page_instruction_seen" in codes
        if page_steered and "ai_cart_mismatch" in codes:
            # Policy (evaluation-plan s.8): a cart that differs from the request on a page that tried to steer the
            # agent is treated as following third-party instructions -> block. Two independent layers agree.
            found.append(Finding("cart_differs_on_manipulated_page", "block",
                                 "The shop page tried to instruct AI agents, and the cart doesn't match what you "
                                 "asked for, so the agent probably followed the page.",
                                 "the cart matches your request", source="ai"))
        decision = escalate(decision, found)
        decision.ai_call = asdict(info) if info else {"error": "unavailable"}
        trace[-1]["codes"] = [f.code for f in found]   # include the two-layer block rule's finding
    decision.trace = trace
    return decision
