"""Money as integer cents. Every limit check in AgentGuard compares cents, never floats (ADR-0007, review A4).

Why: 0.1 + 0.2 != 0.3 in floating point. A cart that is exactly at the buyer's limit must pass, every time.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def to_cents(amount: Decimal | str | float) -> int:
    """Convert an amount in dollars to whole cents. Floats go through str(), so 18.6 means 18.60, not 18.5999..."""
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError(f"not a money amount: {amount!r}") from None
    if not value.is_finite():
        raise ValueError(f"not a money amount: {amount!r}")
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def line_total_cents(unit_price, quantity: int) -> int:
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    return to_cents(unit_price) * quantity


def fmt(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}" if cents >= 0 else "-" + fmt(-cents)
