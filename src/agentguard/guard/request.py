"""What the agent sends. Treated as an untrusted CLAIM (decision D3): facts are re-checked against the
merchant's own records (registry, catalogue prices) before they count."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentguard.mandate import Address


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str
    title: str
    category: str
    unit_price: float = Field(gt=0)          # dollars as the agent states them; converted to cents in checks
    reference_price: float | None = None    # catalogue / market price from the merchant system, not the agent
    quantity: int = Field(ge=1)
    merchant_id: str


class Payee(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merchant_id: str
    display_name: str
    paypal_email: str


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    mandate_id: str
    mandate_version: int
    payee: Payee
    currency: str
    items: list[Item] = Field(min_length=1)
    ship_to: Address
    agent_id: str
    agent_note: str | None = Field(default=None, max_length=2000)   # free text from the agent: untrusted
    kind: Literal["purchase"] = "purchase"
