"""Plain English -> mandate draft. The buyer reviews and approves the draft; nothing is active until then.

The model only fills a schema; every value is then checked against fixed lists (categories, shops) and the
mandate's own validation. Anything it can't map becomes a clarification question, never a guess.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from agentguard.ai.llm import LLM, CallInfo
from agentguard.mandate import Address, Mandate
from agentguard.money import to_cents

SYSTEM = """Turn a shopper's instruction to their AI shopping agent into spending rules. Use ONLY the categories and
shops listed. If the shopper gives one price limit, use it for both budget_total and max_item_price. If something
needed is missing or ambiguous, add a short question to clarifications instead of guessing. Answer in JSON."""


class MandateDraft(BaseModel):
    budget_total: float = Field(gt=0)
    max_item_price: float | None = Field(default=None, gt=0)
    max_quantity_per_item: int = Field(default=1, ge=1, le=100)
    allowed_categories: list[str] = Field(min_length=1)
    allowed_merchants: list[str] = Field(default_factory=list)
    valid_days: int = Field(default=7, ge=1, le=90)
    clarifications: list[str] = Field(default_factory=list, max_length=3)


class DraftResult(BaseModel):
    mandate: Mandate | None
    clarifications: list[str]
    rejected_values: list[str]


def parse(llm: LLM, text: str, *, mandate_id: str, ship_to: Address, categories: list[str],
          merchants: list[str], now: datetime) -> tuple[DraftResult, CallInfo]:
    user = (f"SHOPPER SAYS: {text}\nALLOWED CATEGORIES: {', '.join(categories)}\n"
            f"KNOWN SHOPS: {', '.join(merchants)}\nToday is {now:%Y-%m-%d}.")
    d, info = llm.json(system=SYSTEM, user=user, schema=MandateDraft)
    bad = [c for c in d.allowed_categories if c not in categories] + \
          [m for m in d.allowed_merchants if m not in merchants]
    cats = [c for c in d.allowed_categories if c in categories]
    shops = [m for m in d.allowed_merchants if m in merchants] or list(merchants)
    asks = list(d.clarifications) + ([f"I couldn't match: {', '.join(bad)}. Which did you mean?"] if bad else [])
    if not cats:
        return DraftResult(mandate=None, clarifications=asks or ["What kind of items should the agent buy?"],
                           rejected_values=bad), info
    budget = to_cents(d.budget_total)
    m = Mandate(mandate_id=mandate_id, version=1, buyer_instruction=text, currency="USD", budget_total_cents=budget,
                max_item_price_cents=min(to_cents(d.max_item_price), budget) if d.max_item_price else budget,
                max_quantity_per_item=d.max_quantity_per_item, allowed_categories=tuple(cats),
                allowed_merchants=tuple(shops), ship_to=ship_to, valid_from=now,
                expires_at=now + timedelta(days=d.valid_days))
    return DraftResult(mandate=m, clarifications=asks, rejected_values=bad), info
