"""Signed "receipt of intent": dispute evidence that the buyer's rules allowed this payment.

A receipt holds the exact mandate the buyer approved (so anyone can recompute its SHA-256 fingerprint), what was
bought (from the merchant catalogue, D3), the decision and why, the PayPal ids (the order's custom_id carries the
same fingerprint, D2), and the audit-chain head at issue time. It is signed with Ed25519.

Key: AGENTGUARD_SIGNING_KEY (base64 of a 32-byte Ed25519 private key) in production. Without it a fresh key is made
at start-up and receipts are marked `ephemeral_key` (fine for the demo, worthless as long-term evidence). The private
key never leaves this process; AWS KMS replaces it after the hackathon (ADR-0008 amendment).
"""

import base64
import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agentguard.flow.audit import canonical

ALG = "Ed25519"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


class ReceiptSigner:
    def __init__(self, private_key_b64: str | None = None):
        raw = private_key_b64 if private_key_b64 is not None else os.environ.get("AGENTGUARD_SIGNING_KEY")
        self.ephemeral = not raw
        self._key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw)) if raw else \
            Ed25519PrivateKey.generate()
        self.public_bytes = self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.key_id = hashlib.sha256(self.public_bytes).hexdigest()[:16]

    @property
    def public_key_b64(self) -> str:
        return _b64(self.public_bytes)

    def sign(self, payload: dict) -> dict:
        payload = {**payload, "key_id": self.key_id, "ephemeral_key": self.ephemeral}
        return {"alg": ALG, "receipt": payload, "signature": _b64(self._key.sign(canonical(payload).encode()))}


def verify(doc: dict, public_key_b64: str) -> dict:
    """Check a receipt with only the public key. Every check is reported, so a failure says exactly what broke."""
    checks = {}
    try:
        payload = doc["receipt"]
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(
            base64.b64decode(doc["signature"]), canonical(payload).encode())
        checks["signature"] = True
    except (InvalidSignature, KeyError, ValueError, TypeError):
        checks["signature"] = False
        return {"valid": False, "checks": checks}
    m = payload.get("mandate") or {}
    fp = hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                        .encode()).hexdigest()
    checks["mandate_fingerprint"] = fp == payload.get("mandate_fingerprint")
    checks["paypal_custom_id"] = payload.get("paypal_custom_id") in (None, f"agentguard:{fp}")
    return {"valid": all(checks.values()), "checks": checks}
