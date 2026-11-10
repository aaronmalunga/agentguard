"""Storage for budgets and payments (ADR-0007).

The budget reservation is ONE conditional UPDATE, so two simultaneous requests can never both pass the last
dollars of a budget. The same SQL runs on SQLite (demo, tests) and PostgreSQL. Money is integer cents.
Never release a reservation when the PayPal outcome is unknown.
"""

import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import ClassVar

SCHEMA = """
CREATE TABLE IF NOT EXISTS budgets (
  mandate_id TEXT PRIMARY KEY, budget_cents INTEGER NOT NULL, spent_cents INTEGER NOT NULL DEFAULT 0,
  reserved_cents INTEGER NOT NULL DEFAULT 0,
  CHECK (spent_cents >= 0 AND reserved_cents >= 0 AND spent_cents + reserved_cents <= budget_cents));
CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, mandate_id TEXT NOT NULL, mandate_version INTEGER,
  mandate_fingerprint TEXT, amount_cents INTEGER NOT NULL, currency TEXT NOT NULL, level TEXT NOT NULL,
  status TEXT NOT NULL, findings_json TEXT NOT NULL, facts_json TEXT NOT NULL, agent_note TEXT,
  paypal_order_id TEXT, paypal_authorization_id TEXT, paypal_capture_id TEXT, paypal_status TEXT,
  paypal_debug_id TEXT, ai_json TEXT, trace_json TEXT, cart_json TEXT, page_source TEXT, agent_id TEXT,
  refunded_cents INTEGER NOT NULL DEFAULT 0, dispute_json TEXT, shadow_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paypal_events (
  event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payment_id TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, payment_id TEXT, data_json TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()   # one writer at a time for SQLite; Postgres uses row locks instead
        self._db.executescript(SCHEMA)
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(payments)")}
        for col, ddl in (("refunded_cents", "INTEGER NOT NULL DEFAULT 0"), ("dispute_json", "TEXT"),
                         ("shadow_json", "TEXT")):
            if col not in cols:   # a file database created before 9 Nov (shadow_json: 10 Nov)
                self._db.execute(f"ALTER TABLE payments ADD COLUMN {col} {ddl}")

    @contextmanager
    def _tx(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    # ---- budgets
    def ensure_budget(self, mandate_id: str, budget_cents: int, spent_cents: int = 0):
        with self._tx() as db:
            db.execute("INSERT OR IGNORE INTO budgets (mandate_id, budget_cents, spent_cents) VALUES (?,?,?)",
                       (mandate_id, budget_cents, spent_cents))

    def set_budget(self, mandate_id: str, budget_cents: int):
        """New mandate version with a different budget. The CHECK constraint refuses a budget below what's used."""
        with self._tx() as db:
            db.execute("UPDATE budgets SET budget_cents=? WHERE mandate_id=?", (budget_cents, mandate_id))

    def budget(self, mandate_id: str) -> dict:
        row = self._db.execute("SELECT * FROM budgets WHERE mandate_id=?", (mandate_id,)).fetchone()
        return dict(row) if row else {}

    def reserve(self, mandate_id: str, cents: int) -> bool:
        """Atomic: succeeds only if the amount still fits. No read-then-write gap."""
        with self._tx() as db:
            cur = db.execute("UPDATE budgets SET reserved_cents = reserved_cents + ? WHERE mandate_id = ? "
                             "AND spent_cents + reserved_cents + ? <= budget_cents", (cents, mandate_id, cents))
            return cur.rowcount == 1

    def release(self, mandate_id: str, cents: int):
        with self._tx() as db:
            db.execute("UPDATE budgets SET reserved_cents = reserved_cents - ? WHERE mandate_id = ?",
                       (cents, mandate_id))

    def settle(self, mandate_id: str, cents: int):
        """Reserved money was captured: move it from reserved to spent in one statement."""
        with self._tx() as db:
            db.execute("UPDATE budgets SET reserved_cents = reserved_cents - ?, spent_cents = spent_cents + ? "
                       "WHERE mandate_id = ?", (cents, cents, mandate_id))

    # ---- payments
    def insert_payment(self, **p) -> dict:
        p.setdefault("created_at", now())
        p["updated_at"] = p["created_at"]
        cols = ",".join(p)
        with self._tx() as db:
            db.execute(f"INSERT INTO payments ({cols}) VALUES ({','.join('?' * len(p))})", tuple(p.values()))
        return self.payment(p["id"])

    def update_payment(self, pid: str, **fields) -> dict:
        fields["updated_at"] = now()
        sets = ",".join(f"{k}=?" for k in fields)
        with self._tx() as db:
            db.execute(f"UPDATE payments SET {sets} WHERE id=?", (*fields.values(), pid))
        return self.payment(pid)

    def payment(self, pid: str) -> dict:
        row = self._db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else {}

    def by_request_key(self, key: str) -> dict:
        row = self._db.execute("SELECT * FROM payments WHERE request_key=?", (key,)).fetchone()
        return dict(row) if row else {}

    def payments(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM payments ORDER BY created_at DESC, id DESC")]

    # ---- audit log (hash chain; see agentguard.flow.audit). Append-only: there is no update or delete method.
    def append_audit(self, kind: str, payment_id: str | None, data_json: str,
                     link: Callable[[str, dict], str]) -> dict:
        """Read the chain head and write the next entry in ONE transaction, so two writers can't fork the chain."""
        with self._tx() as db:
            return self._append_audit(db, kind, payment_id, data_json, link)

    @staticmethod
    def _append_audit(db, kind, payment_id, data_json, link) -> dict:
        last = db.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (last["seq"] + 1, last["hash"]) if last else (1, "0" * 64)
        rec = {"seq": seq, "at": now(), "kind": kind, "payment_id": payment_id, "data_json": data_json}
        h = link(prev, rec)
        db.execute("INSERT INTO audit (seq, at, kind, payment_id, data_json, prev_hash, hash) "
                   "VALUES (?,?,?,?,?,?,?)", (seq, rec["at"], kind, payment_id, data_json, prev, h))
        return {**rec, "prev_hash": prev, "hash": h}

    # ---- PayPal events (transactional inbox, review W5)
    BUDGET_SQL: ClassVar[dict[str, str]] = {
        "settle": "UPDATE budgets SET reserved_cents = reserved_cents - ?, spent_cents = spent_cents + ? "
                  "WHERE mandate_id = ?",
        "release": "UPDATE budgets SET reserved_cents = reserved_cents - ? WHERE mandate_id = ?",
        "unspend": "UPDATE budgets SET spent_cents = spent_cents - ? WHERE mandate_id = ?",
    }

    def apply_paypal_event(self, event_id: str, event_type: str, payment_id: str, plan_for: Callable[[dict], object],
                           audit_data: dict, link: Callable[[str, dict], str]) -> dict | None:
        """Record a verified PayPal event exactly once. In ONE transaction: claim the event ID (a repeat hits the
        primary key and changes nothing), re-read the payment, apply the planned status, field and budget changes,
        and append the audit entry. A crash part-way rolls everything back, so PayPal's retry is processed cleanly.
        Returns None for a duplicate, else {"payment": ..., "plan": ...}."""
        with self._tx() as db:
            try:
                db.execute("INSERT INTO paypal_events (event_id, event_type, payment_id, received_at) "
                           "VALUES (?,?,?,?)", (event_id, event_type, payment_id, now()))
            except sqlite3.IntegrityError:
                return None
            p = dict(db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone())
            plan = plan_for(p)
            fields = dict(plan.fields)
            if "dispute_json" in fields:   # merge, so an UPDATED event keeps the evidence attached on CREATED
                old = json.loads(p["dispute_json"]) if p.get("dispute_json") else {}
                fields["dispute_json"] = json.dumps({**old, **{k: v for k, v in fields["dispute_json"].items()
                                                               if v is not None}})
            if plan.status:
                fields["status"] = plan.status
            if plan.budget:
                op, cents = plan.budget
                args = (cents, cents, p["mandate_id"]) if op == "settle" else (cents, p["mandate_id"])
                db.execute(self.BUDGET_SQL[op], args)
            if fields:
                fields["updated_at"] = now()
                db.execute(f"UPDATE payments SET {','.join(f'{k}=?' for k in fields)} WHERE id=?",
                           (*fields.values(), payment_id))
            data = {**audit_data, "status_before": p["status"], "status_after": plan.status or p["status"],
                    "note": plan.note}
            if plan.budget:
                data["budget"] = {"op": plan.budget[0], "cents": plan.budget[1]}
            self._append_audit(db, "paypal_webhook", payment_id, json.dumps(data, sort_keys=True), link)
            p = dict(db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone())
        return {"payment": p, "plan": plan}

    def audit_entries(self, payment_id: str | None = None) -> list[dict]:
        if payment_id:
            rows = self._db.execute("SELECT * FROM audit WHERE payment_id=? ORDER BY seq", (payment_id,))
        else:
            rows = self._db.execute("SELECT * FROM audit ORDER BY seq")
        return [dict(r) for r in rows]
