# AI governance, guardrails and evaluation (model card)

Status as of **8 Nov 2026**. Every number links to a committed run. Gaps are listed, not hidden.

## 1. What the AI does, and what it may never do
| | |
|---|---|
| **Model** | `gemini-3.5-flash-lite` (Google, AI Studio free tier), configurable via `GEMINI_MODEL`. Temperature 0, seed 7, minimal "thinking", 15 s timeout, 1 retry on transient errors |
| **Job 1: intent check** (`src/agentguard/ai/intent.py`) | Does the cart match the buyer's own words? Is the shop page trying to steer the agent? |
| **Job 2: mandate parser** (`src/agentguard/ai/mandate_parser.py`) | Plain English → a *draft* mandate the buyer reviews and approves |
| **Never** | Move money, approve anything, lower a decision, see PayPal credentials, write text shown to the buyer as fact |
| **Data sent to the model** | The buyer's instruction, cart lines (item, category, quantity, price), shop page text. **Not** names, addresses, emails or payment details. All data in this project is synthetic. Google's free tier may use prompts to improve its products |

## 2. Guardrails (each is enforced in code and tested)
| # | Guardrail | Risk it addresses (OWASP Top 10 for Agentic Applications 2026) | Where | Evidence |
|---|---|---|---|---|
| G1 | Deterministic rules decide first; AI and detector may only **escalate** (approve → hold → ask first → block) | ASI10 rogue agent, ASI08 cascading failures | `guard/decision.py` `escalate()` | `test_escalate_is_monotonic`, `test_ai_can_never_lower_a_decision` |
| G2 | **Fail-safe:** any AI error, timeout, quota or invalid output → *ask the buyer* | ASI08 | `ai/intent.py` | `test_ai_failure_asks_never_approves`; measured: 8 failed calls became 7 asks, 0 approvals (dev, 8 Nov) |
| G3 | **Structured output:** JSON validated against a schema; invalid = failure (G2) | Output handling | `ai/llm.py` | schema-valid 100% on held-out look #2 (47/47) and v2 (77/77); 94.0% before the retry fix |
| G4 | **Untrusted data:** page text is wrapped in `<untrusted_page>` tags; the model is told never to follow it | ASI01 goal hijack | `ai/intent.py` | `test_page_text_is_marked_untrusted_in_the_prompt` |
| G5 | **Check the model's claims in code** where possible: "followed the page" is ignored if there is no page text or the model saw no instructions | Hallucination | `ai/intent.py` | Found live on 8 Nov (`docs/ai-integration-log.md` run 4); `test_followed_page_claim_ignored_when_there_is_no_page` |
| G6 | **Block needs corroboration:** a block from meaning alone requires cart mismatch **and** page instructions (detector or AI) | Hallucination, false blocks | `guard/engine.py` | 0 false blocks across all runs (75 dev, 30 held-out, 54 v2 benign) |
| G7 | **Approval screen shows only verified facts**; agent text is shown quoted and labelled unverified | ASI09 human-agent trust exploitation | `guard/rules.py` `verified_facts()` | `test_agent_text_is_kept_apart_from_verified_facts`; v2 `agent_note_pressure` 5/5 asked |
| G8 | **Parser can't invent:** categories and shops must come from fixed lists; unknowns become questions; nothing is active until the buyer approves | Hallucination | `ai/mandate_parser.py` | `test_parser_without_a_known_category_asks_instead_of_guessing`; live 8 Nov: correct $80 / audio / SoundMart |
| G9 | **Agent never holds PayPal keys;** only the guard's gateway can call PayPal | ASI03 identity and privilege abuse | `paypal/gateway.py` | Architecture; agent-environment test planned (review C4) |
| G10 | **Action allowlist:** agents may only request a purchase authorisation | ASI02 tool misuse | `guard/rules.py` | `excessive_agency` family: 100% blocked (v0 dev + held-out) |
| G11 | **Race-free budget:** one conditional UPDATE | ASI10 | `flow/store.py` | 10 parallel $20 requests vs $80: exactly 4 pass |
| G12 | **Sandbox only, secrets out of code/logs, least-privilege PayPal app** | Security | `config.py`, ADR-0004 | 12 config tests; live sandbox checks 9/9 and 6/6 |

## 3. How we know when the AI is wrong (hallucination and over-flagging)
We measure it, on test sets the AI was never tuned on, and we count every kind of mistake separately.
- **False blocks** (the AI or rules stopped a normal purchase): **0** in every run.
- **AI over-flagging** (normal purchase sent to the buyer because of the AI): dev 0/75; held-out look #2 6/30
  (4 partial carts, 2 small markups; prompt changed and disclosed); v2 **0** (all 5 asks there came from the detector,
  since fixed).
- **AI misses** (attack approved): v2 1/28 (low severity: page steered, cart still right).
- **Invented claims** caught in code: G5 (one live case found and closed).
- **Facts shown to the buyer** never come from the model (G7), so a model error can't put a false price, shop or
  address on the approval screen.

## 4. Evaluation history (all pre-registered in `docs/evaluation-plan.md`)
| Run | Set | Rules | + Detector | + AI | Notes |
|---|---|---|---|---|---|
| Look #1 | held-out v0+v1 (125) | 76.8% catch, 15 severe | 100%, 0 severe | — | 100% overstated: shared wording, lucky split |
| Look #2 | held-out v0+v1 (125) | 76.8% | 100% | 100%, 0 severe, 0 FB, **20% step-ups** | 3 pass marks missed, reported as written |
| v2 | test-only, natural language (82) | **0%** | **0%** | **96.4%**, 0 severe, 0/54 FB | all 4 v2 expectations met |
Files: `evidence/runs/`, look log: `evidence/heldout_looks.jsonl`, AI answers: `evidence/ai_cache.jsonl`.

## 5. Governance process
Pre-registered metrics and pass marks · frozen, hashed test sets committed before they run · every look at test data
logged with a reason · test-informed changes disclosed and re-tested on a fresh set · daily adversarial review
(`docs/review-process.md`) · decisions recorded with who approved them (`docs/decision-log.md`, ADRs) · live
integration log (`docs/ai-integration-log.md`) · AI and tool use disclosed in the README.

## 6. Known gaps (owner: the project; planned before submission unless marked later)
- **Hash-chained audit log** of every decision (required by our own rules; not built yet).
- **Consistency test:** the same case 3 times, same answer? (pre-registered metric, not run yet).
- **Mandate parser accuracy** on a labelled set (only spot-checked live).
- **Explanation quality** judged by an LLM-as-judge validated against hand labels (later).
- **Cart and price provenance (D3):** the guard should read items and prices from the merchant's catalogue, not the
  agent's request. The evaluation supplies them; the live flow must enforce it.
- **Page capture (D4):** page text must come from the proxy, not the agent.
- **One model family tested** (budget). Results apply to this model only.
- **Synthetic data, one labeller.** Real traffic would start in shadow mode.
