# Planned vs built (reconciled 11 Nov 2026, before submission)

Every commitment in the brief, the ADRs and the decision log, checked against the code and evidence on 11 Nov.
**Built** items cite their evidence; **not built** items say why and where they went. Nothing below is claimed in the
README, the video or Devpost unless it is in the "Built" table.

## Built (with evidence)
| Commitment | Where promised | Evidence |
|---|---|---|
| Mandates: budget, items, shops, price cap, quantity, expiry; versioned, fingerprinted | Brief s.6 | `mandate.py`; `test_fingerprint_is_stable_and_sensitive`, `test_mandate_versions_only_go_up` |
| AI drafts the mandate from plain English; buyer approves before it applies | Brief s.6 | `/api/mandates/draft`, Your rules screen |
| Orders v2 authorize → capture / void, gated by the guard | Brief s.6, ADR-0001 | `paypal/gateway.py`; live 8/8 (9 Nov) |
| Vault saved card, merchant-initiated, buyer not present | Brief s.6 | `gateway.py` (`stored_credential`); spike results |
| Three layers: rules → hidden-instruction detector → AI intent check (+ line-item check) | Brief s.6 | `guard/`; evaluation v2/v3/held-out |
| Decisions: approve / hold / ask first / block; AI can only escalate; fail-safe = ask | Brief s.6, ADR-0006 | `test_ai_can_never_lower_a_decision`, `test_ai_failure_asks_never_approves` |
| Verified webhooks; forward-only state machine; transactional inbox | Brief s.6, ADR-0009 | live refund check 10 Nov (4/4 verified); webhook tests |
| Signed receipts (Ed25519) + hash-chained audit log | Brief s.6 | `test_receipt_verifies_and_any_change_breaks_it`, `test_audit_chain_verifies_and_detects_tampering` |
| Review console on AG Grid (filters, search, approve / reject in the grid, record panel) | Brief s.6 | live sweep 10 Nov |
| Shadow mode (per mandate; hard limits still act) | Brief s.6/s.8, ADR-0010 | `tests/unit/test_shadow.py`; live check 10 Nov |
| Atomic budget reservation (one conditional UPDATE) | ADR-0007 | `test_parallel_reservations_never_exceed_budget` (10 × $20 vs $80 → exactly 4), on SQLite |
| Idempotency (`PayPal-Request-Id` on every money call) | Brief s.8 | `test_every_money_call_sends_a_request_id`, `test_capture_replay_returns_same_capture_no_double_charge` |
| Per-agent revocable keys + MCP server (4 tools, none moves money) | ADR-0005 amendment | `test_exactly_four_tools_and_none_can_approve_or_move_money` |
| Channel3 market price (soft signal) | Sponsor strategy | live trace "Market price" |
| Channel3 product identity check: listing vs Channel3's record (soft signal, asks first) | Sponsor review, 11 Nov | `test_market.py` (6 tests); live check `evidence/live_checks/2026-11-11_channel3_identity_live.md`; not in the measured attack sets |
| Keyless demo still replays recorded answers (bug fixed 11 Nov) | D14 | `test_without_a_gemini_key_the_scripted_scenarios_still_replay_recorded_answers` |
| Dispute flag + signed evidence attached (not sent) | Stretch | `test_dispute_on_paypal_flags_payment_and_attaches_signed_evidence` |
| Evaluation: rules-only vs full, frozen sets, held-out, pre-registered real-agent runs | Brief s.9 | `evidence/runs/`, `evidence/agent_runs/`, `docs/evaluation-plan.md` |
| Security: CSP, HSTS, rate limits, secrets never logged, threat model | Brief s.8 | `docs/threat-model.md` (all 57 cited tests exist, checked 11 Nov) |
| APIMatic PayPal Context Plugin (build 5 Nov, review 10 Nov) | Sponsor strategy | `docs/apimatic-review-2026-11-11.md` |

## Planned, not built (and where it went)
| Commitment | Where promised | Status and reason | Where it went |
|---|---|---|---|
| **PostgreSQL** storage | ADR-0007 | **Not built.** SQLite only (in memory on the demo); the same atomic statement runs on both | ADR-0007 amendment (11 Nov); v2 durable storage (`production-gaps.md`) |
| **Buyer approves the mandate on PayPal's page (JS SDK v6)** | Brief s.6, decision D2 | **Not built.** The buyer approves in AgentGuard; payments use the Vault saved card. The sandbox approval page was the fallback plan if D2 "fought us" (video plan, 8 Nov) | v2 |
| **Wrap PayPal's own Agent Toolkit / MCP server (proxy)** | Brief s.6 | **Changed.** AgentGuard ships its own MCP server with the same order-tool names (`create_order`, `get_order_details`) instead of proxying PayPal's | v2 (proxy in front of PayPal's server) |
| ML anomaly score (trained locally) | Brief s.6 | Not built; the AI intent check covered the in-limit attacks | README Limitations; evaluation plan s.8 |
| Three-vendor model bake-off; Bedrock | ADR-0006, ADR-0008 | Not run; one model chosen by constraint (free tier) | ADR-0006 amendment |
| AWS services (Budgets, IAM, SSM, KMS, S3 Object Lock, Bedrock, CDK, X-Ray) | ADR-0002, ADR-0008 | Moved after submission (ADR-0008 amendment, 7 Nov); receipts signed with a local key | v2 |
| OpenTelemetry traces | Project instructions; ADR-0002 | Not built; each decision records per-layer timings in its trace instead | v2 list (decision log, 10 Nov) |
| Advisory mode; per-check shadow | Brief s.8, ADR-0010 | Not built | ADR-0010 consequences |
| Auto-void of held payments before PayPal's honour period | Decision D2, spike v2 | Designed, not built | README Limitations |
| Disputes API evidence upload | Stretch, ADR-0009 | Evidence prepared, not sent (API unverified) | ADR-0009; production gaps |
| Refund guard (agent-initiated refunds) | Stretch, ADR-0003 | Not built; refunds made on PayPal are tracked via webhooks | Evaluation plan ("not in v0") |
| Pay Later / responsible-credit rule | Stretch | Not built | v2 candidate |
| Know-your-agent: per-agent keypairs, signed requests | Stretch | **Changed.** Per-agent revocable bearer keys (stored as fingerprints) instead of keypairs | decision log, 10 Nov |
| Postman collection; OpenAPI → generated AgentGuard SDK | Sponsor strategy | Not built (no prize; time) | `production-gaps.md` (deferred) |
| AG Grid extras: group by agent, risk-score cell, master/detail rows, live updates, override → feedback labels | Brief s.6 | Not built; the console has filters, search, approve/reject in the grid and a side record panel | v2 |
| MLflow experiment tracking | Brief s.9 | Not used; every run is a committed JSON file in `evidence/runs/` | — |
| LLM-as-judge for explanation clarity (+ 50 hand labels) | Brief s.9 | Not built | evaluation plan s.8 |
| Explanation faithfulness test | ADR-0006 | Not needed in v1: explanations are templated from the rule that fired; no LLM rewording exists | — |
| NL → mandate parsing accuracy; repeated-run variance; cost per decision | Brief s.9 | Not measured | v2 evaluation notebook |
| Guard p95 < 300 ms | Evaluation plan, ADR-0006 | **Missed for the AI path** (AI p95 1.7–2.3 s); rules and detector ~0.3 ms | evaluation plan, results table |
| "No guard" baseline | Brief s.9 | Not run as a separate config: with no guard every attack is paid by definition (0 caught) | — |
| Runbook | Brief s.8 | Not written | v2 |
| Fees for a $40 refund vs void | Video plan | Measured once in the sandbox ($1.53 vs $0.00) | Proof page, README |

## How this list is kept honest
- Re-check before any public text (README, Devpost, video): every claim must sit in the "Built" table.
- Old drafts (`SUBMISSION_DRAFT.md`, `SUBMISSION_FORM.md` in the planning folder) list tools we did not use (React,
  Postman); the final Devpost text is written fresh from this file and `interview-prep/METRICS.md`.
