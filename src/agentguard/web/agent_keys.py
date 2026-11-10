"""Per-agent keys (review M1, 10 Nov): the buyer connects an agent, the agent gets its own revocable key.

Why: with one shared agent token, the agent ID on a payment is whatever the agent wrote in its request, which is a
claim, not a fact. A per-agent key lets AgentGuard record the agent it actually knows, revoke one agent without
touching the others, and let an agent running elsewhere (an MCP client on a laptop) act inside the buyer's own demo
session. Keys follow the same rule as everything else the agent sends: the server decides, the agent claims.

- The key is shown once, when minted. Only its SHA-256 is kept, so a leaked database does not leak working keys.
- A key belongs to one demo session; requests with it act inside that session (its budget, payments and log).
- A key can only ask to pay (the agent role). It can never approve, reject, set rules or read the log.
- Revoked keys answer 401 "revoked". At most MAX_PER_SESSION keys per session.
"""

import hashlib
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

PREFIX = "agk_"
MAX_PER_SESSION = 5


@dataclass
class AgentKey:
    agent_id: str
    name: str
    session: str
    created_at: str
    revoked: bool = False
    digest: str = field(default="", repr=False)

    def public(self) -> dict:
        return {"agent_id": self.agent_id, "name": self.name, "created_at": self.created_at, "revoked": self.revoked}


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class AgentKeys:
    def __init__(self):
        self._by_digest: dict[str, AgentKey] = {}
        self._lock = threading.Lock()

    def mint(self, session: str, name: str) -> tuple[str, AgentKey]:
        with self._lock:
            live = [k for k in self._by_digest.values() if k.session == session and not k.revoked]
            if len(live) >= MAX_PER_SESSION:
                raise ValueError(f"At most {MAX_PER_SESSION} active agent keys per session; revoke one first.")
            key = PREFIX + secrets.token_urlsafe(24)
            rec = AgentKey(agent_id="agt_" + secrets.token_hex(6), name=name, session=session,
                           created_at=datetime.now(UTC).isoformat(timespec="seconds"), digest=_digest(key))
            self._by_digest[rec.digest] = rec
            return key, rec

    def lookup(self, key: str) -> AgentKey | None:
        """Constant-time compare on the digest, so key checks don't leak timing."""
        d = _digest(key)
        with self._lock:
            for stored, rec in self._by_digest.items():
                if secrets.compare_digest(stored, d):
                    return rec
        return None

    def for_session(self, session: str) -> list[AgentKey]:
        with self._lock:
            return [k for k in self._by_digest.values() if k.session == session]

    def revoke(self, session: str, agent_id: str) -> AgentKey | None:
        with self._lock:
            for rec in self._by_digest.values():
                if rec.session == session and rec.agent_id == agent_id:
                    rec.revoked = True
                    return rec
        return None

    def known(self, agent_id: str | None) -> bool:
        with self._lock:
            return bool(agent_id) and any(r.agent_id == agent_id for r in self._by_digest.values())
