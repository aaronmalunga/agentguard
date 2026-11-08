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
import secrets
import uuid
from collections.abc import Callable
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
DEMO_ANSWERS = Path(__file__).parent / "demo_ai_answers.jsonl"   # made by scripts/record_demo_answers.py
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
class State:
    def __init__(self, *, paypal_mode: str, llm, layers, clock, signer, tokens, db_path: str):
        self.paypal_mode, self.llm, self.layers, self.clock = paypal_mode, llm, layers, clock
        self.signer, self.tokens, self.db_path = signer, tokens, db_path
        self.gateway, self.payment_source = self._paypal()
        self.reset()

    def _paypal(self):
        if self.paypal_mode == "sandbox":
            from agentguard.config import load_settings
            vault_id = os.environ.get("AGENTGUARD_VAULT_ID")
            if not vault_id:
                raise RuntimeError("AGENTGUARD_PAYPAL=sandbox needs AGENTGUARD_VAULT_ID "
                                   "(run scripts/create_vault.py once)")
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

    def reset(self):
        self.svc = PaymentService(Store(self.db_path), self.gateway, mandates={}, registry=demo.REGISTRY,
                                  payment_source=self.payment_source, clock=self.clock, layers=self.layers,
                                  llm=self.llm, catalogue=demo.catalogue(), merchant_names=demo.NAMES,
                                  signer=self.signer)
        self.pages: dict[str, dict] = {}
        for key, sc in demo.SCENARIOS.items():
            self.add_page(sc["page"], f"SoundMart: {sc['label']}", "demo shop (synthetic)", page_id=f"demo-{key}")
        self.svc.activate_mandate(demo.demo_mandate(self.clock()))

    def add_page(self, text: str, title: str, source: str, page_id: str | None = None) -> dict:
        pid = page_id or "page_" + uuid.uuid4().hex[:12]
        self.pages[pid] = {"id": pid, "title": title, "text": text, "source": source,
                           "sha256": hashlib.sha256(text.encode()).hexdigest(),
                           "captured_at": self.clock().isoformat(timespec="seconds")}
        return self.pages[pid]


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
               tokens: dict | None = None, demo_mode: bool | None = None, db_path: str | None = None) -> FastAPI:
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
    st = State(paypal_mode=paypal_mode, llm=llm if ai != "off" else None, layers=layers,
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

    @app.middleware("http")
    async def label_mode(request: Request, call_next):
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
                "audit_entries": a["checked"], "demo": demo_mode}

    # ---------------------------------------------------------------- shop data (public)
    @app.get("/api/catalogue", tags=["shop"])
    def catalogue():
        return {"source": "synthetic demo data", "merchant": demo.MERCHANT_NAME,
                "products": [{**p.__dict__, "price": fmt(p.price_cents),
                              "reference_price": fmt(p.reference_price_cents) if p.reference_price_cents else None}
                             for p in demo.PRODUCTS]}

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
        def session():
            """Public demo only: hands the browser the demo tokens. Never enabled with real tokens."""
            if st.tokens != DEMO_TOKENS:
                _err(404, "not_found", "Demo session is off.")
            return {"buyer_token": st.tokens["buyer"], "agent_token": st.tokens["agent"]}

        @app.get("/api/demo/scenarios", tags=["demo"])
        def scenarios():
            return [{"id": k, "label": v["label"], "expect": v["expect"], "page_id": f"demo-{k}"}
                    for k, v in demo.SCENARIOS.items()]

        @app.post("/api/demo/run", tags=["demo"], dependencies=[buyer])
        def run(body: RunIn):
            """Run the scripted demo agent on a scenario or a pasted page, through the same guard as any agent."""
            sc = demo.SCENARIOS.get(body.scenario or "")
            page_id = f"demo-{body.scenario}" if sc else body.page_id
            pg = st.pages.get(page_id or "") or _err(422, "unknown_scenario", "Give a known scenario or page_id.")
            m = st.svc.mandates.get("thandi-earbuds") or next(iter(st.svc.mandates.values()))
            cart = demo.naive_agent_cart(pg["text"], m, sc["lines"] if sc else None,
                                         sc.get("claimed_price") if sc else None)
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
