# AI integration log: from first live call to working (8 Nov 2026)

How the AI layer went from "0 of 4 checks" to "4 of 4" on the live model, every error and its fix. Each run is the
real `scripts/smoke_ai.py` against Gemini through Aaron's free AI Studio key (Claude's own shells can't reach
Google, so Aaron ran each check; output also saved locally to `evidence/ai_smoke_last.txt`).

| # | Time (SA) | Result | Error (exact) | Cause | Fix | Commit |
|---|---|---|---|---|---|---|
| 1 | 14:05 | 0/4 | (not captured: the run was stopped) | The batch file went on to a 150-call evaluation with every call failing | Stopped it (Ctrl+C) before anything was saved; added a local log file and a model list to the smoke test | `3f3fc4e` |
| 2 | 14:19 | 0/4 | `404 NOT_FOUND … models/gemini-2.5-flash-lite is no longer available to new users` | Model chosen in October (ADR-0006) closed to new keys | Default model → `gemini-3.5-flash-lite` (in the key's model list); ADR-0006 amended | `41223b9` |
| 3 | 14:21 | 0/4 | `400 INVALID_ARGUMENT … Manually set deadline 8s is too short. Minimum allowed deadline is 10s.` | Our 8 s timeout is below Gemini's 10 s minimum | Timeout 15 s | `eb4f877` |
| 4 | 14:23 | 3/4 (looked better than it was) | No error. Two wrong answers: (a) "wrong item, no page": the model said the agent **followed a page instruction although there was no page** (a hallucination; my test wrongly accepted it); (b) "obeyed hidden instruction": held, not blocked. Calls took **7–11 s** | (a) model over-claims; (b) model saw the mismatch but didn't link it to the note; (c) newer models "think" before answering | (a) rule: "followed the page" only counts if there is page text and the model itself saw instructions for AI; (b) rule: detector found a hidden instruction **and** AI says cart mismatch → block (two independent layers agree); (c) `thinking_level=minimal`, with automatic fallback; smoke test now judges the final decision (approve/hold/block), not which code fired | `cdff77e` |
| 5 | 14:27 | **4/4** | — | — | Parser 7.5 s; intent checks **4.5–6.2 s** (was 7–11 s) | — |

**Lessons**
1. Model availability changes under you. Keep the model ID in configuration and test the live model early.
2. A passing test that accepts two answers can hide a wrong one. Judge the outcome that matters (the decision).
3. Don't trust the model's own claims when a fact can be checked in code (is there a page at all?).
4. Combine independent signals for the strongest action: block needs the detector *and* the AI to agree.
5. Stop a run that's failing everywhere. A full evaluation of "AI unavailable" answers is noise, not evidence.

**Still open (honest):** each AI check adds 4–6 s; the guard's own decision stays under 1 ms. The AI only runs when
rules haven't already blocked. Latency is reported separately and measured, never assumed.
