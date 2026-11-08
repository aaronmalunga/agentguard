"""Deterministic mandate rules: the base decision. No AI here, so it is repeatable and testable.

Thresholds were tuned on the DEV split only (evaluation-plan.md s.4). Every finding says, in plain words, why
it fired and what would make the payment pass (counterfactual explanations, N4).
"""

from datetime import datetime

from agentguard.guard.decision import Finding
from agentguard.guard.request import PaymentRequest
from agentguard.mandate import Mandate
from agentguard.money import fmt, line_total_cents, to_cents

ALLOWED_ACTIONS = {"authorize_purchase"}
PRICE_HOLD_RATIO = 1.20   # page price more than 20% above the catalogue price -> hold (tuned on dev)


def check(request: PaymentRequest, mandate: Mandate | None, *, now: datetime, registry: dict[str, str],
          spent_cents: int) -> list[Finding]:
    f: list[Finding] = []
    add = f.append

    # 1. Action allowlist (OWASP ASI02 tool misuse / excessive agency)
    if request.action not in ALLOWED_ACTIONS:
        add(Finding("action_not_allowed", "block",
                    f"The agent asked to '{request.action}'. Agents may only request a purchase authorisation; "
                    "capturing, refunding and payouts are done by AgentGuard or the merchant.", None))

    # 2. Mandate identity, version, status, dates
    if mandate is None or mandate.mandate_id != request.mandate_id:
        add(Finding("unknown_mandate", "block", f"No mandate '{request.mandate_id}' exists for this buyer.",
                    "the agent cites a mandate the buyer actually approved"))
        return f   # nothing else can be checked without the buyer's rules
    if request.mandate_version != mandate.version:
        add(Finding("stale_mandate_version", "block",
                    f"The agent used rules version {request.mandate_version}; the buyer's current rules are "
                    f"version {mandate.version}.", f"the request follows version {mandate.version}"))
    if mandate.status != "active":
        add(Finding("mandate_revoked", "block", "The buyer has revoked these rules.",
                    "the buyer approves a new mandate"))
    if now < mandate.valid_from:
        add(Finding("mandate_not_yet_valid", "block", f"These rules start on {mandate.valid_from:%d %b %Y}.",
                    f"the purchase happens on or after {mandate.valid_from:%d %b %Y}"))
    if now > mandate.expires_at:
        add(Finding("mandate_expired", "block", f"These rules expired on {mandate.expires_at:%d %b %Y}.",
                    "the buyer renews the mandate"))

    # 3. Currency
    if request.currency != mandate.currency:
        add(Finding("currency_mismatch", "block",
                    f"Payment is in {request.currency}; the buyer's rules are in {mandate.currency}.",
                    f"the payment is in {mandate.currency}"))

    # 4. Who gets paid: allowlisted merchant AND that merchant's real PayPal account (registry, not the agent)
    p = request.payee
    if p.merchant_id not in mandate.allowed_merchants:
        add(Finding("payee_not_allowed", "block",
                    f"'{p.display_name}' is not one of the shops the buyer allowed "
                    f"({', '.join(mandate.allowed_merchants)}).",
                    f"the buyer adds '{p.merchant_id}' to the allowed shops"))
    elif registry.get(p.merchant_id) != p.paypal_email:
        add(Finding("payee_account_mismatch", "block",
                    f"The money would go to a PayPal account that isn't {p.display_name}'s registered account.",
                    "the payment goes to the merchant's registered PayPal account"))

    # 5. Each item
    total = 0
    for it in request.items:
        price = to_cents(it.unit_price)
        total += line_total_cents(it.unit_price, it.quantity)
        if it.category not in mandate.allowed_categories:
            add(Finding("category_not_allowed", "block",
                        f"'{it.title}' is in '{it.category}', which the buyer didn't allow "
                        f"({', '.join(mandate.allowed_categories)}).",
                        f"the cart drops '{it.title}', or the buyer allows '{it.category}'"))
        if it.merchant_id not in mandate.allowed_merchants:
            add(Finding("item_merchant_not_allowed", "block",
                        f"'{it.title}' is sold by '{it.merchant_id}', not an allowed shop.",
                        "the item comes from an allowed shop"))
        if price > mandate.max_item_price_cents:
            add(Finding("item_over_max_price", "block",
                        f"'{it.title}' costs {fmt(price)}, above the {fmt(mandate.max_item_price_cents)} per-item "
                        "limit.", f"the price is at most {fmt(mandate.max_item_price_cents)}, or the buyer raises "
                        f"the per-item limit to {fmt(price)}"))
        if it.quantity > mandate.max_quantity_per_item:
            add(Finding("quantity_over_max", "block",
                        f"{it.quantity} × '{it.title}' is more than the {mandate.max_quantity_per_item} allowed.",
                        f"the quantity is at most {mandate.max_quantity_per_item}"))
        if it.reference_price and price > to_cents(it.reference_price) * PRICE_HOLD_RATIO:
            ref = to_cents(it.reference_price)
            add(Finding("price_above_reference", "hold",
                        f"'{it.title}' is {fmt(price)} here, {round(100 * (price - ref) / ref)}% above its usual "
                        f"{fmt(ref)}.", f"the price is at most {fmt(int(ref * PRICE_HOLD_RATIO))}"))

    # 6. Budget (snapshot check; the atomic reservation in storage is the real guard against races, ADR-0007)
    remaining = mandate.budget_total_cents - spent_cents
    if total > remaining:
        add(Finding("over_budget", "block",
                    f"This order is {fmt(total)}, but only {fmt(max(remaining, 0))} of the "
                    f"{fmt(mandate.budget_total_cents)} budget is left.",
                    f"the order is at most {fmt(max(remaining, 0))}, or the buyer raises the budget by "
                    f"{fmt(total - remaining)}"))

    # 7. Delivery address: the place is a hard limit; a new recipient name alone is a manipulation signal
    if not mandate.ship_to.same_place(request.ship_to):
        add(Finding("ship_to_changed", "block",
                    f"Delivery goes to {request.ship_to.line1}, {request.ship_to.city}, not the buyer's address.",
                    "the order ships to the address in the mandate"))
    elif request.ship_to.name != mandate.ship_to.name:
        add(Finding("recipient_changed", "ask_first",
                    f"Same address, but the parcel is addressed to '{request.ship_to.name}' instead of "
                    f"'{mandate.ship_to.name}'.", f"the recipient is '{mandate.ship_to.name}', or the buyer confirms"))
    return f


def verified_facts(request: PaymentRequest, mandate: Mandate | None, spent_cents: int) -> dict:
    """What the approval screen may show: facts checked by AgentGuard, never agent wording (OWASP ASI09)."""
    total = sum(line_total_cents(i.unit_price, i.quantity) for i in request.items)
    facts = {"shop": request.payee.display_name, "total": fmt(total),
             "items": [{"title": i.title, "quantity": i.quantity, "price": fmt(to_cents(i.unit_price)),
                        "usual_price": fmt(to_cents(i.reference_price)) if i.reference_price else None}
                       for i in request.items],
             "ship_to": f"{request.ship_to.name}, {request.ship_to.line1}, {request.ship_to.city}"}
    if mandate is not None:
        facts["budget_left"] = fmt(mandate.budget_total_cents - spent_cents)
        facts["rules_version"] = mandate.version
    return facts
