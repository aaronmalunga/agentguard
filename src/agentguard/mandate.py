"""The mandate: what the buyer allowed their agent to buy. Signed, versioned, never edited in place.

- Money is integer cents (agentguard.money). Limits are inclusive.
- A mandate is immutable. Changing a rule makes a NEW version (revise()), so every decision can cite the exact rules
  that applied (audit log, receipts, dispute evidence).
- fingerprint() is a SHA-256 of the canonical JSON. It is what receipts sign and what goes in the PayPal order's
  custom_id (decision D2), so anyone can check the rules weren't changed after the fact.
"""

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentguard.money import to_cents


class Address(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1)
    line1: str = Field(min_length=1)
    city: str = Field(min_length=1)
    postal_code: str = Field(min_length=1)
    country: str = Field(pattern=r"^[A-Z]{2}$")

    def same_place(self, other: "Address") -> bool:
        """Hard limit compares the place only; a different recipient name is a soft signal (evaluation-plan s.3)."""
        return (self.line1, self.city, self.postal_code, self.country) == \
               (other.line1, other.city, other.postal_code, other.country)


class Mandate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mandate_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    buyer_instruction: str = Field(min_length=1, max_length=2000)
    currency: Literal["USD"]
    budget_total_cents: int = Field(gt=0)
    max_item_price_cents: int = Field(gt=0)
    max_quantity_per_item: int = Field(ge=1)
    allowed_categories: tuple[str, ...] = Field(min_length=1)
    allowed_merchants: tuple[str, ...] = Field(min_length=1)
    ship_to: Address
    valid_from: datetime
    expires_at: datetime
    status: Literal["active", "revoked"] = "active"

    @model_validator(mode="after")
    def consistent(self):
        if self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be after valid_from")
        if self.max_item_price_cents > self.budget_total_cents:
            raise ValueError("max item price can't exceed the total budget")
        if self.valid_from.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("dates must include a timezone")
        return self

    def is_valid_at(self, now: datetime) -> bool:
        return self.status == "active" and self.valid_from <= now <= self.expires_at

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def revise(self, **changes) -> "Mandate":
        """New version with changes applied. The old version stays valid evidence of what was allowed before."""
        if "version" in changes or "mandate_id" in changes:
            raise ValueError("version and mandate_id are managed by revise()")
        return Mandate.model_validate({**self.model_dump(), **changes, "version": self.version + 1})

    def revoke(self) -> "Mandate":
        return self.revise(status="revoked")

    @classmethod
    def from_catalogue(cls, m: dict) -> "Mandate":
        """Build from an attack-catalogue mandate (dollars as floats) without changing its meaning."""
        return cls(
            mandate_id=m["mandate_id"], version=m["version"], buyer_instruction=m["buyer_instruction"],
            currency=m["currency"], budget_total_cents=to_cents(m["budget_total"]),
            max_item_price_cents=to_cents(m["max_item_price"]), max_quantity_per_item=m["max_quantity_per_item"],
            allowed_categories=tuple(m["allowed_categories"]), allowed_merchants=tuple(m["allowed_merchants"]),
            ship_to=Address(**m["ship_to"]), valid_from=m["valid_from"], expires_at=m["expires_at"],
            status=m["status"])
