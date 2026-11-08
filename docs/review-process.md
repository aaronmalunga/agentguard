# How we review our own work (adversarial loop)

AgentGuard is reviewed against itself on purpose: after each build step we switch sides and try to break what we just
made, the way a sceptical judge, security reviewer or customer would. Started 5 Nov 2026; **runs every build day**.

## The loop
1. **Build** a layer (code, data, or a decision).
2. **Attack it.** Ask: what would a payments-security engineer, an ML evaluator, a test lead, a product manager or a
   developer advocate find wrong? Check claims against the data and the source, not memory.
3. **Classify** each finding: *Fixed* (done now), *Planned* (owner + day), or *Open* (needs a human decision).
4. **Decide.** Claude proposes options with a recommendation; Aaron approves, changes or rejects. Approvals are
   recorded with date and time.
5. **Record** it in the dated review file, the decision log, and (for numbers) METRICS.md. Pre-registered evaluation
   rules are never edited silently: changes go in `evaluation-plan.md` section 8 with date and reason.

## Log
| Date | Review | Findings | Fixed same day | Decisions | Biggest change it caused |
|---|---|---|---|---|---|
| 5 Nov 2026 | [review-2026-11-05.md](review-2026-11-05.md) | 22 | 3 (rules-only ceiling → catalogue v1; smoke test saves on failure; fake's replay status) | D1–D4 approved by Aaron 15:24; D5–D6 deferred | Froze 120 in-limit attack cases **before any rule existed**, so the AI is judged where rules can't see |
| 8 Nov 2026 | Full requirements + criteria review (project hub `FOOLPROOF_REVIEW.md`) | 12 risks ranked | — (review before the build) | D7–D11 proposed | Found that AI must do meaningful work *in the product* (Stage 1), so AI moves to the first build item; new safeguards: approval screens resist manipulation (OWASP ASI09), threat model mapped to the OWASP Top 10 for Agentic Applications 2026 |
| 8 Nov 2026 (pm) | Held-out look #1 (`docs/evaluation-plan.md` s.8) | 2 (lucky split; shared attack wording) | Detector frozen at `5e48324`; v2 independent-wording catalogue pre-registered | — | Turned a 100% score into an honest claim and a stronger next test |
| 8 Nov 2026 (14:23) | First live AI run (`docs/ai-integration-log.md`) | 3 (hallucinated page claim; missed block; 7–11 s latency) | 3 fixed in 4 minutes | — | Rules around the model: verify its claims in code; block only when two layers agree |
| 8 Nov 2026 (15:28) | Catalogue v2 run (`docs/evaluation-plan.md` s.8) | 4 (held not blocked; 1 approved attack; detector false positive; smaller set) | — (recorded; test-set findings fixed only with disclosure) | — | Proved where the AI matters: rules 0% → AI 96.4% on natural-language attacks |
| 8 Nov 2026 (evening) | [review-2026-11-08-api.md](review-2026-11-08-api.md) | 13 | 8 (padding attack past the AI's 4,000-char window; circular receipt check; agent self-approval; agent-set prices/payee/page; error shape; fake-mode label) | D14 (AI quota) open | Found that a long page could hide an instruction from the AI, and that the free AI quota can silently turn the demo into "ask for everything" |
| 8 Nov 2026 (19:15) | [review-2026-11-08-ui.md](review-2026-11-08-ui.md) | 9 | 5 (wrong budget label, grid actions off-screen, re-drawn chrome, disabled states, contrast/spacing) | U7 logo file (Aaron) | Hallmark sloplint 3 FAIL / 29 REFLEX → 0 / 0; found that judges would share one demo budget |

## Why we do this
Judges aren't required to run the project, so every claim must survive a reader who assumes it is wrong. Finding our
own holes first is cheaper than a judge finding them, and the record shows how the design improved, not just where it
ended up.
