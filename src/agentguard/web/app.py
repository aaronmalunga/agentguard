"""AgentGuard web API. Run: `uv run uvicorn agentguard.web.app:app --reload` (keyless demo by default).

Trust boundaries (OWASP ASI02/ASI03):
- The AGENT token can only ask to pay (POST /api/payments). It can't approve, capture, refund or read the log.
- The BUYER token approves rules and answers holds. In the demo the buyer also sees the merchant console.
- Prices, titles and the payee account come from the merchant catalogue (D3); page text from AgentGuard's own page
  capture, referenced by page_id (D4). The agent's own words are kept, quoted, as `agent_note` (untrusted).

Environment: AGENTGUARD_PAYPAL=fake|sandbox (default fake = FakePayPal, labelled everywhere) ·
GEMINI_API_KEY (AI layer; without it the AI check fails safe to "ask the buyer") · AGENTGUARD_AI=off (disable AI,
labelled) · AGENTGUARD_VAULT_ID (sandbox: the buyer's saved card, made by scripts/create_vault.py) ·
AGENTGUARD_SIGNING_KEY (receipts) · AGENTGUARD_AGENT_TOKEN / AGENTGUARD_BUYER_TOKEN · AGENTGUARD_DEMO=1.
"""

import hashlib
import json
import os
import re
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import requests
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from agentguard.ai import mandate_parser
from agentguard.ai.llm import AIUnavailable
from agentguard.flow.catalogue import AgentCart
from agentguard.flow.receipts import ReceiptSigner
from agentguard.flow.receipts import verify as verify_receipt
from agentguard.flow.service import FlowError, PaymentService
from agentguard.flow.store import Store
from agentguard.guard.engine import LAYERS
from agentguard.mandate import Mandate
from agentguard.money import fmt
from agentguard.paypal import PayPalGateway, vaulted_card
from agentguard.web import demo

STATIC = Path(__file__).parent / "static"
DEMO_ANSWERS = Path(__file__).parent / "demo_ai_answers.jsonl"
RUNS = Path(__file__).resolve().parents[3] / "evidence" / "runs"
PROOF_RUNS = {"v3": "20261108T140724Z_v3.json", "v2": "20261108T132205Z_v2.json"}   # frozen test-only sets
FEE_EVIDENCE = {"capture_cents": 4000, "refund_fee_lost_cents": 153, "void_fee_cents": 0,
                "source": "PayPal sandbox merchant account, 14 Oct 2026 (US sandbox; live fees vary)",
                "evidence": "docs/evidence/*fee.png, *void-no-fee.png"}   # made by scripts/record_demo_answers.py
DEMO_TOKENS = {"agent": "demo-agent-token", "buyer": "demo-buyer-token"}


class NoAI:
    """Stands in when no model key is set: every AI check fails safe to 'ask the buyer' (never silently skipped)."""
    model = "none (no GEMINI_API_KEY)"

    def json(self, **_):
        raise AIUnavailable("no AI model configured")


def _err(status: int, code: str, message: str):
    raise HTTPException(status, {"code": code, "message": message})


# ------------------------------------------------------------------------------------------------ request bodies
class PaymentIn(AgentCart):
    page_id: str | None = Field(default=None, max_length=64)   # page AgentGuard captured; text never from agent


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=3, max_length=2000)


class MandateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mandate: Mandate


class PageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)
    title: str = Field(default="Pasted page", max_length=120)


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str | None = None
    page_id: str | None = None


# ------------------------------------------------------------------------------------------------ app state
SESSION_COOKIE = "ag_demo"
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
MAX_SESSIONS, SESSION_IDLE_S = 200, 2 * 3600
_current: ContextVar[str] = ContextVar("agentguard_session", default="default")

# Per-IP limit on the calls that spend PayPal sandbox or AI quota (judge test, 9 Nov). The public demo hands out its
# tokens, so a loop could otherwise burn the shared Gemini free tier for every judge. Reads and checks are not limited.
COSTLY = re.compile(r"^/api/(demo/run|pages|mandates/draft|payments|payments/[^/]+/(approve|reject))$")


class RateLimiter:
    """Sliding 60-second window per client. In memory, one process: enough for the demo, not for a cluster."""

    def __init__(self, per_min: int):
        self.per_min, self.hits, self._lock = per_min, {}, threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = [t for t in self.hits.get(key, []) if now - t < 60]
            if len(q) >= self.per_min:
                self.hits[key] = q
                return False, int(60 - (now - q[0])) + 1
            q.append(now)
            self.hits[key] = q
            if len(self.hits) > 5000:   # forget the oldest clients; bounded memory
                for k in list(self.hits)[:1000]:
                    del self.hits[k]
            return True, 0


def client_ip(request: Request) -> str:
    """Render runs behind Cloudflare, which sets True-Client-IP to the visitor's address and overwrites any value a
    client sends. Render's own X-Forwarded-For entry is its proxy (it changes per request, so it can't be the key:
    found on the live site, 9 Nov). Off Render (local, tests) fall back to the socket address."""
    ip = request.headers.get("true-client-ip") or request.headers.get("cf-connecting-ip")
    return ip.strip() if ip else (request.client.host if request.client else "unknown")


class Session:
    """One visitor's demo: their own budget, payments, pages and hash-chained log (review U6, 9 Nov).
    PayPal gateway, AI model and receipt signing key are shared."""

    def __init__(self, st: "State", db_path: str):
        self.st, self.db_path, self.last_seen = st, db_path, time.monotonic()
        self.reset()

    def reset(self):
        st = self.st
        self.svc = PaymentService(Store(self.db_path), st.gateway, mandates={}, registry=demo.REGISTRY,
                                  payment_source=st.payment_source, clock=st.clock, layers=st.layers,
                                  llm=st.llm, catalogue=st.demo.catalogue(st.market), merchant_names=demo.NAMES,
                                  signer=st.signer)
        self.pages: dict[str, dict] = {}
        for key, sc in st.demo.scenarios.items():
            self.add_page(sc["page"], f"SoundMart: {sc['label']}", "demo shop (synthetic)", page_id=f"demo-{key}")
        self.svc.activate_mandate(demo.demo_mandate(st.clock()))

    def add_page(self, text: str, title: str, source: str, page_id: str | None = None) -> dict:
        pid = page_id or "page_" + uuid.uuid4().hex[:12]
        self.pages[pid] = {"id": pid, "title": title, "text": text, "source": source,
                           "sha256": hashlib.sha256(text.encode()).hexdigest(),
                           "captured_at": self.st.clock().isoformat(timespec="seconds")}
        return self.pages[pid]


class State:
    def __init__(self, *, paypal_mode: str, llm, layers, clock, signer, tokens, db_path: str, demo_data, market):
        self.paypal_mode, self.llm, self.layers, self.clock = paypal_mode, llm, layers, clock
        self.signer, self.tokens, self.db_path = signer, tokens, db_path
        self.demo, self.market = demo_data, market
        self.gateway, self.payment_source = self._paypal()
        self.sessions: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()
        self.session()   # the shared "default" session: API clients without a demo cookie (agents, scripts, tests)

    def session(self, sid: str | None = None) -> Session:
        sid = sid or _current.get()
        with self._lock:
            now = time.monotonic()
            for old in [k for k, v in self.sessions.items() if k != "default" and now - v.last_seen > SESSION_IDLE_S]:
                del self.sessions[old]
            s = self.sessions.get(sid)
            if s is None:
                s = self.sessions[sid] = Session(self, self.db_path if sid == "default" else ":memory:")
                while len(self.sessions) > MAX_SESSIONS:
                    victim = next(k for k in self.sessions if k != "default")
                    del self.sessions[victim]
            s.last_seen = now
            self.sessions.move_to_end(sid)
            return s

    # the current request's session (set by middleware from the demo cookie)
    @property
    def svc(self) -> PaymentService:
        return self.session().svc

    @property
    def pages(self) -> dict:
        return self.session().pages

    def add_page(self, *a, **kw) -> dict:
        return self.session().add_page(*a, **kw)

    def reset(self):
        self.session().reset()

    def _paypal(self):
        if self.paypal_mode == "sandbox":
            from agentguard.config import load_settings
            vault_id = os.environ.get("AGENTGUARD_VAULT_ID")
            if not vault_id:
                raise RuntimeError("AGENTGUARD_PAYPAL=sandbox needs AGENTGUARD_VAULT_ID "
                                   "(run scripts/smoke_api.py once)")
            return PayPalGateway(load_settings()), (lambda _m: vaulted_card(vault_id))
        from agentguard.config import load_settings
        from agentguard.paypal.fake import FakePayPal
        self.fake = FakePayPal()
        self.fake.vault.add("VAULT-DEMO-FAKE")
        s = requests.Session()
        s.mount("https://", self.fake)
        gw = PayPalGateway(load_settings(paypal_env="sandbox", paypal_client_id="fake", paypal_client_secret="fake",
                                         _env_file=None), http_client_instance=s)
        return gw, (lambda _m: vaulted_card("VAULT-DEMO-FAKE"))


def view(p: dict) -> dict:
    """A payment as the API shows it: JSON fields parsed, money formatted, whether PayPal was ever called."""
    out = {k: v for k, v in p.items() if not k.endswith("_json")}
    for k in ("findings", "facts", "ai", "cart", "trace"):
        raw = p.get(f"{k}_json")
        out[k] = json.loads(raw) if raw else None
    out["amount"] = fmt(p["amount_cents"])
    out["paypal_called"] = bool(p.get("paypal_order_id"))
    return out


# ------------------------------------------------------------------------------------------------ factory
def create_app(*, paypal_mode: str | None = None, llm=None, ai: str | None = None,
               clock: Callable[[], datetime] | None = None, signer: ReceiptSigner | None = None,
               tokens: dict | None = None, demo_mode: bool | None = None, db_path: str | None = None,
               demo_source: str = "auto", market=None,
               rate_per_min: int | None = None) -> FastAPI:
    from dotenv import load_dotenv  # same .env files as the scripts; real env vars win

    from agentguard.config import ENV_FILES
    for f in ENV_FILES:
        load_dotenv(f, override=False)
    paypal_mode = paypal_mode or os.environ.get("AGENTGUARD_PAYPAL", "fake")
    if paypal_mode not in ("fake", "sandbox"):
        raise RuntimeError("AGENTGUARD_PAYPAL must be 'fake' or 'sandbox' (live PayPal is never allowed)")
    ai = ai or os.environ.get("AGENTGUARD_AI", "on")
    layers = LAYERS if ai != "off" else ("rules", "detector")
    if llm is None and ai != "off":
        if os.environ.get("GEMINI_API_KEY"):
            from agentguard.ai.llm import GeminiLLM
            llm = GeminiLLM()
        else:
            llm = NoAI()
        from agentguard.ai.cache import (
            RecordedFirstLLM,  # D14: scripted scenarios replay recorded real answers
        )
        if DEMO_ANSWERS.exists():
            llm = RecordedFirstLLM(DEMO_ANSWERS, inner=None if isinstance(llm, NoAI) else llm, model=llm.model)
    demo_mode = demo_mode if demo_mode is not None else os.environ.get("AGENTGUARD_DEMO", "1") == "1"
    tokens = tokens or {"agent": os.environ.get("AGENTGUARD_AGENT_TOKEN") or DEMO_TOKENS["agent"],
                        "buyer": os.environ.get("AGENTGUARD_BUYER_TOKEN") or DEMO_TOKENS["buyer"]}
    if market is None and os.environ.get("CHANNEL3_API_KEY"):
        from agentguard.market.channel3 import Channel3
        market = Channel3()
    st = State(paypal_mode=paypal_mode, llm=llm if ai != "off" else None, layers=layers, demo_data=demo.build(demo_source),
               market=market,
               clock=clock or (lambda: datetime.now(UTC)), signer=signer or ReceiptSigner(), tokens=tokens,
               db_path=db_path or os.environ.get("AGENTGUARD_DB", ":memory:"))

    app = FastAPI(title="AgentGuard API", version="0.2.0",
                  description="Checks that an AI agent's payment is what the buyer meant, before money moves on "
                              "PayPal (sandbox only). Agents ask; AgentGuard decides; PayPal moves the money.")
    app.state.ag = st

    @app.exception_handler(HTTPException)
    async def http_error(_req: Request, exc: HTTPException):
        body = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
        return JSONResponse({"error": body}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def bad_request(_req: Request, exc: RequestValidationError):
        """Same error shape everywhere (API contract): code, message, and which fields were wrong."""
        fields = [{"field": ".".join(str(x) for x in e["loc"][1:]), "problem": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": {"code": "invalid_request", "message": "The request doesn't match the API "
                                       "schema.", "fields": fields}}, status_code=422)

    rate_per_min = rate_per_min if rate_per_min is not None else int(os.environ.get("AGENTGUARD_RATE_PER_MIN", "30"))
    limiter = RateLimiter(rate_per_min) if rate_per_min > 0 else None

    @app.middleware("http")
    async def label_mode(request: Request, call_next):
        if limiter and request.method == "POST" and COSTLY.match(request.url.path):
            ok, wait = limiter.allow(client_ip(request))
            if not ok:
                return JSONResponse({"error": {"code": "rate_limited", "message": f"Too many paid calls from this "
                                     f"address ({limiter.per_min} a minute). Try again in {wait} s."}},
                                    status_code=429, headers={"Retry-After": str(wait)})
        sid = request.cookies.get(SESSION_COOKIE, "")
        _current.set(sid if demo_mode and SESSION_ID.match(sid) else "default")   # per-visitor demo (U6)
        resp = await call_next(request)
        resp.headers["X-AgentGuard-PayPal"] = st.paypal_mode   # "fake" responses are simulated, never PayPal
        return resp

    @app.exception_handler(FlowError)
    async def flow_error(_req: Request, exc: FlowError):
        return JSONResponse({"error": {"code": "invalid_state", "message": str(exc)}}, status_code=409)

    def role(*allowed: str):
        def check(authorization: str | None = Header(default=None)):
            token = (authorization or "").removeprefix("Bearer ").strip()
            who = next((r for r, t in st.tokens.items() if secrets.compare_digest(token, t)), None)
            if who is None:
                _err(401, "unauthenticated", "Send 'Authorization: Bearer <token>'.")
            if who not in allowed:
                _err(403, "forbidden", f"The {who} role can't do this. Allowed: {', '.join(allowed)}.")
            return who
        return Depends(check)

    agent, buyer = role("agent"), role("buyer")

    # ---------------------------------------------------------------- health and mode labels
    @app.get("/healthz", tags=["meta"])
    def healthz():
        a = st.svc.verify_audit()
        return {"ok": a["ok"], "paypal": "PayPal sandbox" if st.paypal_mode == "sandbox"
                else "FakePayPal (simulated, no real PayPal calls)",
                "ai": "off (rules + detector only)" if st.llm is None else getattr(st.llm, "model", "unknown"),
                "receipt_key": "ephemeral (demo)" if st.signer.ephemeral else "configured",
                "audit_entries": a["checked"], "demo": demo_mode,
                "market": "Channel3 (live market prices)" if st.market is not None else "off",
                "product_data": st.demo.source,
                "recorded_ai_answers": sum(1 for _ in DEMO_ANSWERS.open(encoding="utf-8")) if DEMO_ANSWERS.exists() else 0}

    # ---------------------------------------------------------------- shop data (public)
    @app.get("/api/catalogue", tags=["shop"])
    def catalogue():
        return {"source": st.demo.source, "merchant": f"{demo.MERCHANT_NAME} (a made-up shop)",
                "products": [{**p.__dict__, "price": fmt(p.price_cents),
                              "reference_price": fmt(p.reference_price_cents) if p.reference_price_cents else None}
                             for p in st.demo.products]}

    @app.get("/api/pages/{page_id}", tags=["shop"])
    def page(page_id: str):
        return st.pages.get(page_id) or _err(404, "not_found", f"No captured page '{page_id}'.")

    @app.post("/api/pages", tags=["shop"], status_code=201, dependencies=[buyer])
    def add_page(body: PageIn):
        """Red-team panel: paste any page text; the scripted agent will read it."""
        return st.add_page(body.text, body.title, "pasted by a user (red-team)")

    # ---------------------------------------------------------------- mandates (buyer)
    @app.post("/api/mandates/draft", tags=["mandates"], dependencies=[buyer])
    def draft(body: DraftIn):
        """Plain English → draft rules (AI). Nothing is active until the buyer approves it."""
        if st.llm is None:
            _err(503, "ai_off", "The AI layer is off; fill in the rules form instead.")
        mid = "m_" + uuid.uuid4().hex[:10]
        try:
            res, info = mandate_parser.parse(st.llm, body.instruction, mandate_id=mid, ship_to=demo.HOME,
                                             categories=demo.CATEGORIES, merchants=demo.MERCHANTS, now=st.clock())
        except AIUnavailable as e:
            _err(503, "ai_unavailable", f"The AI couldn't draft rules right now ({str(e)[:80]}). "
                                        "Fill in the form instead.")
        return {"draft": res.mandate.model_dump(mode="json") if res.mandate else None,
                "clarifications": res.clarifications, "rejected_values": res.rejected_values,
                "ai": {"model": info.model, "latency_ms": info.latency_ms}, "active": False}

    @app.post("/api/mandates", tags=["mandates"], status_code=201, dependencies=[buyer])
    def approve_mandate(body: MandateIn):
        """The buyer approves rules (new mandate, or the next version of one). Old versions stay as evidence."""
        m = st.svc.activate_mandate(body.mandate)
        return {"mandate": m.model_dump(mode="json"), "fingerprint": m.fingerprint(), "active": True}

    @app.get("/api/mandates", tags=["mandates"], dependencies=[buyer])
    def mandates():
        return [{"mandate": m.model_dump(mode="json"), "fingerprint": m.fingerprint(),
                 "budget": st.svc.store.budget(m.mandate_id)} for m in st.svc.mandates.values()]

    # ---------------------------------------------------------------- payments
    @app.post("/api/payments", tags=["payments"], dependencies=[agent])
    def submit(body: PaymentIn, idempotency_key: str | None = Header(default=None, max_length=128)):
        """The agent asks to pay. Same Idempotency-Key ⇒ same answer, nothing happens twice."""
        if not idempotency_key:
            _err(400, "idempotency_key_required", "Send an 'Idempotency-Key' header (one per purchase attempt).")
        pg = st.pages.get(body.page_id) if body.page_id else None
        if body.page_id and pg is None:
            _err(422, "unknown_page", f"No captured page '{body.page_id}'.")
        cart = AgentCart.model_validate(body.model_dump(exclude={"page_id"}))
        p = st.svc.submit_cart(cart, request_key=idempotency_key, page_text=pg["text"] if pg else "",
                               page_source=f"{pg['id']} sha256:{pg['sha256'][:16]}" if pg else None)
        return view(p)

    @app.get("/api/payments", tags=["payments"], dependencies=[buyer])
    def payments():
        return [view(p) for p in st.svc.store.payments()]

    def one(pid: str) -> dict:
        return st.svc.store.payment(pid) or _err(404, "not_found", f"No payment '{pid}'.")

    @app.get("/api/payments/{pid}", tags=["payments"], dependencies=[buyer])
    def payment(pid: str):
        return {**view(one(pid)), "audit": st.svc.store.audit_entries(pid)}

    @app.post("/api/payments/{pid}/approve", tags=["payments"], dependencies=[buyer])
    def approve(pid: str):
        one(pid)
        return view(st.svc.buyer_approve(pid))

    @app.post("/api/payments/{pid}/reject", tags=["payments"], dependencies=[buyer])
    def reject(pid: str):
        one(pid)
        return view(st.svc.buyer_reject(pid))

    @app.get("/api/budget/{mandate_id}", tags=["payments"], dependencies=[buyer])
    def budget(mandate_id: str):
        b = st.svc.store.budget(mandate_id) or _err(404, "not_found", f"No budget for '{mandate_id}'.")
        return {**b, "left": fmt(b["budget_cents"] - b["spent_cents"] - b["reserved_cents"])}

    # ---------------------------------------------------------------- evidence
    @app.get("/api/proof", tags=["evidence"])
    def proof():
        """Measured results, read from the committed evaluation runs (never typed in by hand)."""
        sets = []
        for name, fname in PROOF_RUNS.items():
            f = RUNS / fname
            if not f.exists():
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
            cfg = {}
            for key, c in d["configs"].items():
                a = c["all"]
                cfg[key] = {k: a.get(k) for k in ("cases", "attacks", "benign", "caught", "catch_rate", "catch_ci95",
                                                   "severe_misses", "false_blocks", "step_ups")}
                if "ai" in c:
                    cfg[key]["ai"] = {k: c["ai"].get(k) for k in ("model", "latency_ms_p50", "latency_ms_p95",
                                                                  "fresh_calls", "failures")}
            sets.append({"set": name, "file": f"evidence/runs/{fname}", "frozen_at_commit": d.get("git_commit"),
                         "synthetic": d.get("synthetic_data", True), "run_at": d.get("run_at"), "configs": cfg})
        return {"sets": sets, "fees": FEE_EVIDENCE}

    @app.get("/api/payments/{pid}/receipt", tags=["evidence"], dependencies=[buyer])
    def receipt(pid: str):
        one(pid)
        return st.svc.receipt(pid)

    @app.get("/api/receipts/public-key", tags=["evidence"])
    def public_key():
        return {"alg": "Ed25519", "key_id": st.signer.key_id, "public_key": st.signer.public_key_b64,
                "ephemeral": st.signer.ephemeral}

    @app.post("/api/receipts/verify", tags=["evidence"])
    def verify(doc: Annotated[dict, Body()], public_key: str | None = None):
        """Check a receipt: signature, mandate fingerprint, PayPal custom_id. Pass `public_key` (published in the
        repo) to check against a key you got elsewhere, not the one this server reports (no trust in us needed).
        Offline: scripts/verify_receipt.py."""
        return verify_receipt(doc, public_key or st.signer.public_key_b64)

    @app.get("/api/audit", tags=["evidence"], dependencies=[buyer])
    def audit_log():
        return st.svc.store.audit_entries()

    @app.get("/api/audit/verify", tags=["evidence"])
    def audit_verify():
        return st.svc.verify_audit()

    # ---------------------------------------------------------------- demo helpers
    if demo_mode:
        @app.get("/api/demo/session", tags=["demo"])
        def session(request: Request):
            """Public demo only: hands the browser the demo tokens and its own demo session (own budget, payments
            and log), so judges never see or spend each other's demo. Never enabled with real tokens."""
            if st.tokens != DEMO_TOKENS:
                _err(404, "not_found", "Demo session is off.")
            sid = request.cookies.get(SESSION_COOKIE, "")
            fresh = not SESSION_ID.match(sid)
            if fresh:
                sid = secrets.token_urlsafe(18)
            st.session(sid)
            resp = JSONResponse({"buyer_token": st.tokens["buyer"], "agent_token": st.tokens["agent"],
                                 "session": "own" if sid != "default" else "shared"})
            if fresh:
                resp.set_cookie(SESSION_COOKIE, sid, max_age=SESSION_IDLE_S, httponly=True, samesite="lax",
                                secure=request.url.scheme == "https")
            return resp

        @app.get("/api/demo/scenarios", tags=["demo"])
        def scenarios():
            return [{"id": k, "label": v["label"], "expect": v["expect"], "page_id": f"demo-{k}"}
                    for k, v in st.demo.scenarios.items()]

        @app.post("/api/demo/run", tags=["demo"], dependencies=[buyer])
        def run(body: RunIn):
            """Run the scripted demo agent on a scenario or a pasted page, through the same guard as any agent."""
            sc = st.demo.scenarios.get(body.scenario or "")
            page_id = f"demo-{body.scenario}" if sc else body.page_id
            pg = st.pages.get(page_id or "") or _err(422, "unknown_scenario", "Give a known scenario or page_id.")
            m = st.svc.mandates.get("thandi-earbuds") or next(iter(st.svc.mandates.values()))
            cart = demo.naive_agent_cart(pg["text"], m, sc["lines"] if sc else None,
                                         sc.get("claimed_price") if sc else None, products=st.demo.products)
            steps = [f"Agent opened {pg['title']}",
                     f"Agent chose: {', '.join(f'{ln.quantity} × {ln.sku}' for ln in cart.lines)}",
                     "Agent asked AgentGuard to pay"]
            p = st.svc.submit_cart(cart, request_key="demo-" + uuid.uuid4().hex,
                                   page_text=pg["text"], page_source=f"{pg['id']} sha256:{pg['sha256'][:16]}")
            return {"steps": steps, "page": pg, "payment": view(p)}

        @app.post("/api/demo/reset", tags=["demo"], dependencies=[buyer])
        def reset():
            st.reset()
            return {"ok": True}

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(STATIC / "index.html")

    return app


def __getattr__(name):   # `uvicorn agentguard.web.app:app` builds the app on first access, not on import
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
