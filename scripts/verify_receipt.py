"""Verify an AgentGuard receipt offline, with only the published public key (no need to trust our server).

  uv run python scripts/verify_receipt.py receipt.json <public_key_base64>
  uv run python scripts/verify_receipt.py --new-key      # make a signing key for AGENTGUARD_SIGNING_KEY
"""

import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from agentguard.flow.receipts import ReceiptSigner, verify

if __name__ == "__main__":
    if sys.argv[1:] == ["--new-key"]:
        raw = Ed25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        key = base64.b64encode(raw).decode()
        print("AGENTGUARD_SIGNING_KEY=" + key + "   (keep secret; env var only)")
        print("public key (publish this):", ReceiptSigner(key).public_key_b64)
        sys.exit(0)
    doc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = verify(doc, sys.argv[2])
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)
