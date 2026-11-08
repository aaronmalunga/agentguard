"""Guard entry point: rules first (base decision), then later layers that may only escalate.

Layers: "rules" (deterministic), "detector" (local, no AI call), "ai" (LLM intent check, ADR-0006).
The AI layer is skipped when the payment is already blocked (no point spending a call), and any AI failure
becomes "ask the buyer".
"""

from dataclasses import asdict
from datetime import datetime

from agentguard.guard import detector, rules
from agentguard.guard.decision import Decision, Finding, combine, escalate
from agentguard.guard.request import PaymentRequest
from agentguard.mandate import Mandate

LAYERS = ("rules", "detector", "ai")


def evaluate(request: PaymentRequest, mandate: Mandate | None, *, now: datetime, registry: dict[str, str],
             spent_cents: int, page_text: str = "", layers: tuple[str, ...] = LAYERS, llm=None) -> Decision:
    decision = combine(rules.check(request, mandate, now=now, registry=registry, spent_cents=spent_cents),
                       verified_facts=rules.verified_facts(request, mandate, spent_cents),
                       agent_note=request.agent_note)
    if "detector" in layers:
        decision = escalate(decision, detector.scan(page_text))
    if "ai" in layers and llm is not None and mandate is not None and decision.level != "block":
        from agentguard.ai import intent
        found, info = intent.check(llm, request, mandate, page_text)
        codes = {f.code for f in decision.findings}
        if "hidden_instruction" in codes and any(f.code == "ai_cart_mismatch" for f in found):
            # Policy (evaluation-plan s.8): a cart that differs from the request on a page that tried to steer the
            # agent is treated as following third-party instructions -> block. Two independent layers agree.
            found.append(Finding("cart_differs_on_manipulated_page", "block",
                                 "The shop page tried to instruct AI agents, and the cart doesn't match what you "
                                 "asked for, so the agent probably followed the page.",
                                 "the cart matches your request", source="ai"))
        decision = escalate(decision, found)
        decision.ai_call = asdict(info) if info else {"error": "unavailable"}
    return decision
