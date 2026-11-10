"""Decision levels and findings.

Levels, least to most cautious (decision D1, 5 Nov):
- approve    within the mandate; authorise and capture.
- hold       doubt about price or item: authorise (funds held), buyer approves -> capture, rejects -> void ($0 fee).
- ask_first  a sign of manipulation: nothing is sent to PayPal until the buyer says yes.
- block      breaks a hard mandate limit or is a forbidden action: PayPal is never called.

Monotonic rule (ADR-0006): later checks (detector, AI) can only move a decision UP this list, never down.
"""

from dataclasses import dataclass, field
from typing import Literal

Level = Literal["approve", "hold", "ask_first", "block"]
RANK: dict[str, int] = {"approve": 0, "hold": 1, "ask_first": 2, "block": 3}
EVAL_LABEL = {"approve": "approve", "hold": "ask", "ask_first": "ask", "block": "block"}


@dataclass(frozen=True)
class Finding:
    code: str                    # stable id, e.g. "item_over_max_price"
    level: Level
    reason: str                  # plain English, written by AgentGuard (never by the agent)
    would_pass_if: str | None    # counterfactual (N4): what would make this pass
    source: Literal["rules", "catalogue", "detector", "ai"] = "rules"


@dataclass
class Decision:
    level: Level
    findings: list[Finding] = field(default_factory=list)
    verified_facts: dict = field(default_factory=dict)   # shown on the approval screen (OWASP ASI09)
    agent_note: str | None = None                        # agent-written text: shown quoted, labelled unverified
    ai_call: dict | None = None                          # model id, latency, tokens (evidence log)
    trace: list = field(default_factory=list)            # per layer: name, ms, codes it raised (decision trace UI)

    @property
    def eval_label(self) -> str:
        return EVAL_LABEL[self.level]


# Shadow mode (ADR-0010): only the buyer's own hard limits still act. A block raised by the mandate rules or by the
# shop's catalogue (unknown product, out of stock) is enforced; every other finding is logged as "would have".
ENFORCED_SOURCES_IN_SHADOW = ("rules", "catalogue")


def enforced_in_shadow(f: Finding) -> bool:
    return f.level == "block" and f.source in ENFORCED_SOURCES_IN_SHADOW


def apply_shadow(decision: Decision) -> dict:
    """Shadow mode: lower the decision to what the hard limits alone require, and return the record of what the full
    guard WOULD have done. Shadow can only ever relax judgement checks; it never relaxes a hard limit."""
    logged = [f.code for f in decision.findings if not enforced_in_shadow(f)]
    applied: Level = "block" if any(enforced_in_shadow(f) for f in decision.findings) else "approve"
    record = {"mode": "shadow", "would_have": decision.level, "applied": applied, "logged_only": logged}
    decision.level = applied
    return record


def stricter(a: Level, b: Level) -> Level:
    return a if RANK[a] >= RANK[b] else b


def combine(findings: list[Finding], **extra) -> Decision:
    level: Level = "approve"
    for f in findings:
        level = stricter(level, f.level)
    return Decision(level=level, findings=sorted(findings, key=lambda f: -RANK[f.level]), **extra)


def escalate(decision: Decision, new: list[Finding]) -> Decision:
    """Add findings from a later layer. Can only raise the level (monotonic)."""
    merged = combine([*decision.findings, *new], verified_facts=decision.verified_facts,
                     agent_note=decision.agent_note, ai_call=decision.ai_call)
    assert RANK[merged.level] >= RANK[decision.level]
    return merged
