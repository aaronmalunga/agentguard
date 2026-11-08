"""Guard entry point: rules first (base decision), then later layers that may only escalate."""

from datetime import datetime

from agentguard.guard import detector, rules
from agentguard.guard.decision import Decision, combine, escalate
from agentguard.guard.request import PaymentRequest
from agentguard.mandate import Mandate

LAYERS = ("rules", "detector")   # + "ai" once the LLM intent check is plugged in


def evaluate(request: PaymentRequest, mandate: Mandate | None, *, now: datetime, registry: dict[str, str],
             spent_cents: int, page_text: str = "", layers: tuple[str, ...] = LAYERS) -> Decision:
    decision = combine(rules.check(request, mandate, now=now, registry=registry, spent_cents=spent_cents),
                       verified_facts=rules.verified_facts(request, mandate, spent_cents),
                       agent_note=request.agent_note)
    if "detector" in layers:
        decision = escalate(decision, detector.scan(page_text))
    return decision
