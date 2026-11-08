"""Merchant catalogue lookup (decision D3: never trust the agent's cart).

The agent says WHICH products and HOW MANY (sku + quantity). Title, category, price and seller come from the
merchant's own catalogue, never from the agent. If the agent also states a price or title and it differs from the
catalogue, that is a sign the agent was misled (or is lying), so it becomes a finding.

`reference_price` is an independent market price (Channel3 when connected; otherwise the demo catalogue's own
"usual price", labelled synthetic). It can only raise "hold" via the price rule, never block.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from agentguard.guard.decision import Finding
from agentguard.guard.request import Item
from agentguard.mandate import Address
from agentguard.money import fmt, to_cents


@dataclass(frozen=True)
class Product:
    sku: str
    title: str
    category: str
    price_cents: int
    merchant_id: str
    reference_price_cents: int | None = None
    reference_source: str = "synthetic demo data"
    in_stock: bool = True


class CartLine(BaseModel):
    """What the agent may say about one line. Anything else is ignored by design."""
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=100)
    claimed_price: float | None = Field(default=None, gt=0)       # agent's claim, only compared, never used
    claimed_title: str | None = Field(default=None, max_length=200)


class Catalogue:
    def __init__(self, products: list[Product]):
        self.products = {p.sku: p for p in products}

    def get(self, sku: str) -> Product | None:
        return self.products.get(sku)

    def resolve(self, lines: list[CartLine]) -> tuple[list[Item], list[Finding]]:
        """Build the cart from the catalogue. Unknown SKUs block; agent claims that disagree are findings."""
        items, found = [], []
        for line in lines:
            p = self.products.get(line.sku)
            if p is None:
                found.append(Finding("unknown_product", "block",
                                     f"The agent asked to buy '{line.sku}', which this shop doesn't sell.",
                                     "the cart only contains products from the shop's catalogue",
                                     source="catalogue"))
                continue
            if not p.in_stock:
                found.append(Finding("out_of_stock", "block", f"'{p.title}' is out of stock, so it can't be sold.",
                                     "the item is back in stock", source="catalogue"))
            if line.claimed_price is not None and to_cents(line.claimed_price) != p.price_cents:
                found.append(Finding("agent_price_differs", "ask_first",
                                     f"The agent said '{p.title}' costs {fmt(to_cents(line.claimed_price))}, but the "
                                     f"shop's own price is {fmt(p.price_cents)}. AgentGuard uses the shop's price.",
                                     "the agent's price matches the shop's records, or you confirm",
                                     source="catalogue"))
            if line.claimed_title and line.claimed_title.strip().lower() != p.title.lower():
                found.append(Finding("agent_title_differs", "ask_first",
                                     f"The agent described this item as '{line.claimed_title[:80]}', but the shop's "
                                     f"records say '{p.title}'.", "the agent's description matches the shop's "
                                     "records, or you confirm", source="catalogue"))
            items.append(Item(sku=p.sku, title=p.title, category=p.category, unit_price=p.price_cents / 100,
                              reference_price=(p.reference_price_cents / 100) if p.reference_price_cents else None,
                              quantity=line.quantity, merchant_id=p.merchant_id))
        return items, found


class AgentCart(BaseModel):
    """The agent's request in the live flow. No prices, titles or payee account: AgentGuard looks those up."""
    model_config = ConfigDict(extra="forbid")
    action: str = Field(max_length=64)
    mandate_id: str = Field(max_length=64)
    mandate_version: int
    merchant_id: str = Field(max_length=64)
    lines: list[CartLine] = Field(min_length=1, max_length=20)
    ship_to: Address | None = None            # None = the buyer's address in the mandate
    agent_id: str = Field(max_length=64)
    agent_note: str | None = Field(default=None, max_length=2000)   # untrusted free text, shown quoted
