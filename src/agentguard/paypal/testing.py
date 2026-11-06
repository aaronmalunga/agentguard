"""SANDBOX TEST HELPERS ONLY. Never imported by product code (a test enforces this).

AgentGuard itself never handles card numbers. In production the buyer's card is saved through PayPal-hosted card
fields or a PayPal-wallet vault setup, and AgentGuard only ever sees the resulting vault id (review finding B2).
"""

from paypalserversdk.api_helper import APIHelper
from paypalserversdk.models.card_attributes import CardAttributes
from paypalserversdk.models.card_request import CardRequest
from paypalserversdk.models.payment_source import PaymentSource
from paypalserversdk.models.vault_instruction_base import VaultInstructionBase


def sandbox_test_card(name: str = "Alex Rivera", save: bool = False) -> PaymentSource:
    """PayPal's PUBLIC sandbox test card (from PayPal's docs). Sandbox setup and tests only.
    A name of "CCREJECT-REFUSED" makes the sandbox decline it."""
    return PaymentSource(card=CardRequest(
        name=name, number="4012888888881881", expiry="2030-12", security_code="123",
        attributes=CardAttributes(vault=VaultInstructionBase(store_in_vault="ON_SUCCESS")) if save else APIHelper.SKIP))
