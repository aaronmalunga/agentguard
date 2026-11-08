# Adversarial review: web API, catalogue pricing (D3), audit chain, receipts (8 Nov 2026, evening)

Scope: what was built since commit `07d44c7`: FastAPI web API (`src/agentguard/web/`), catalogue lookup in the live
flow (`flow/catalogue.py`), hash-chained decision log (`flow/audit.py`), Ed25519 receipts (`flow/receipts.py`),
plus the v3 / regression evaluation runs Aaron finished at 16:20. Method: `docs/review-process.md`. Judge lenses are
inference from their profiles (project hub `JUDGE_DOSSIER.md`).

## Hard gates (Stage 1, pass/fail)
| Gate | Status | Gap |
|---|---|---|
| AI does meaningful work in the product | **Yes in code**: every `/api/payments` and `/api/mandates/draft` call goes through Gemini; failure ⇒ ask the buyer | Not yet seen live through the API (Claude's shell can't reach Google/PayPal) → `scripts/windows/api_checks.bat` |
| PayPal sandbox central | Yes: same gateway, now behind HTTP; sandbox mode needs a vault id (`scripts/smoke_api.py` makes one) | Live API run pending (same bat) |
| Functional app judges can use | API only; no screens; not hosted | UI Mon–Tue; Render Tue |
| Video | Not made | Tue |

## Findings
| # | Finding (what a sceptic would say) | Severity | Status |
|---|---|---|---|
| F1 | "Your verify page checks receipts with a key your own server reports: circular." | Medium | **Fixed**: `/api/receipts/verify?public_key=…` and offline `scripts/verify_receipt.py`; test proves a foreign key fails |
| F2 | Receipts signed with an ephemeral key become unverifiable after a restart | High for the hosted demo | **Planned (Tue, Render)**: set `AGENTGUARD_SIGNING_KEY` (`verify_receipt.py --new-key`), publish the public key in the README. `/healthz` shows "ephemeral" until then |
| F3 | Default DB is in memory: a Render restart wipes payments and the audit chain | Medium | **Planned (Tue)**: SQLite file path via `AGENTGUARD_DB`; free tier has no persistent disk, so the demo reseeds and says so (ties to D8) |
| F4 | `/api/demo/session` hands anyone the buyer token | Low (by design) | **Fixed**: only when the tokens are the public demo defaults; a test proves real tokens are never returned |
| F5 | "A hash chain can be rewritten by whoever owns the database." | Medium | **Disclosed** in `audit.py`; each receipt carries the chain head (second copy). **Planned (after submission)**: anchor the head in S3 Object Lock (ADR-0008) |
| F6 | Padding attack: a page longer than 4,000 characters hides an instruction past what the AI reads | **High** | **Fixed**: pages over 4,000 characters ⇒ ask first (`page_too_long_to_check`), tested. Added in the flow layer, not the frozen engine, so no frozen evaluation component changed |
| F7 | 422 errors had FastAPI's own shape, others ours: an inconsistent contract (Postman/Himraj lens) | Low | **Fixed**: one error shape `{"error": {code, message, fields}}`, tested |
| F8 | A screenshot from fake mode could pass as PayPal | Medium (real-over-simulated rule) | **Fixed**: every response carries `X-AgentGuard-PayPal: fake|sandbox`; `/healthz` says "FakePayPal (simulated)" |
| F9 | **Gemini free-tier quota (429).** Today's regression runs: dev 19/131 AI calls failed; held-out look #3 47/47 failed. A judge clicking the demo after a busy day would see every payment "asked" | **High** (R4) | **Open → D14** |
| F10 | Anyone with the demo token can spam `/api/demo/run` and burn the AI quota | Medium | **Planned (Tue)**: per-IP rate limit on demo endpoints |
| F11 | Agent could set its own price, title, payee account or page text | High | **Fixed (D3/D4 enforced)**: request schema forbids those fields (422); prices/titles from the catalogue; payee from the registry; page text by `page_id` from AgentGuard's capture. Agent's stated price that differs ⇒ ask first. 4 tests |
| F12 | Agent could approve its own held payment (excessive agency, S8) | High | **Fixed**: agent and buyer tokens are separate roles; agent on approve ⇒ 403, tested |
| F13 | Rival Proof of Intent signs intent with a **buyer-held** key; our receipt is signed by AgentGuard | Medium (Innovation) | **Accepted, don't overclaim**: we present receipts as engineering ("decision + reasons + AI model + PayPal ids + chain head, verifiable offline"), not as novel. Buyer-side signing = roadmap |

## Our own claims, attacked
- **v3 result (all 5 pre-registered v3 expectations met)** is clean: frozen at `608d01d` before the run, run at that
  commit, 1/110 AI calls failed. ✔
- **Held-out look #3 is NOT an AI measurement**: every AI call failed with 429, so it measured the fail-safe, not the
  AI. Report it that way. What it does prove: with the AI completely down, 0 attacks got through and 0 good purchases
  were blocked. The cost was 25/30 good purchases asked (83%).
- Dev rerun: 19/131 AI calls failed (429); its 97.8% catch includes fail-safe asks. Don't quote it as the AI's accuracy.

## Decision needed (Open)
**D14: keep the AI working for judges and the video (quota).** Options:
1. Turn on billing for the Gemini key (paid tier, same model). Today's v3 run used 41k input + 9k output tokens
   (≈ 110 calls). Recommendation: **yes**, plus a Google Cloud budget alert at $5 (total budget ≤ ~$30).
2. Replay recorded AI answers for the 5 scripted scenarios, labelled "AI answer replayed from cache" on screen;
   live calls for pasted pages. Cheap and safe, but it is replay, so it must be labelled.
3. A second free model as fallback (e.g. a Gemma model on the same key). Different quota, unmeasured accuracy: we
   would have to evaluate it first.
**Recommendation: 1 + 2** (live by default, replay only as a labelled fallback when the provider refuses).
After quota resets: rerun held-out with AI as **look #4**, reason "look #3 invalid: provider quota", logged.

## Tests actually run (8 Nov, Aaron's laptop shell, Python 3.12)
`pytest`: **155 passed** (was 129 at `00b1a8e`), coverage **91%** (1,302 statements). `ruff`: clean.
Server boots under uvicorn; OpenAPI lists 20 paths. Live sandbox + live AI through the API: **not run yet**.
