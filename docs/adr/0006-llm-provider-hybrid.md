# ADR-0006: LLM provider — provider-agnostic, model chosen by bake-off, Bedrock on AWS deploy

- **Status:** Accepted; amended 8 Nov and 9 Nov (bake-off not run, model chosen by constraint; see the end)
- **Date:** 2026-10-14
- **Deciders:** Aaron (decision), Claude (options and analysis)
- **Related:** ADR-0002 (Render + AWS, AWS gated on 30 Oct), ADR-0005 (Strands agent, framework-free guard)

## Context

AgentGuard needs an LLM for two untrusted-side components only:

- the demo shopping agent (Strands);
- the natural-language → mandate parser. Its output is schema-validated and approved by the human.

The guard decision path is deterministic, with p95 < 300 ms, so it makes no synchronous hosted-LLM call. Its injection detector is local.

Explanations are templated from the rule that fired; an optional LLM rewording is checked by the faithfulness test.

Constraints:

- The AWS account is not active until ~25 Oct, and the mandate parser starts 19 Oct.
- Total budget target is ≤ ~$25.
- Project rule: no service is chosen without evaluating the realistic alternatives, with evaluation depth matched to the cost of being wrong.

## Options considered

1. **Direct Anthropic API only.** Available now, strong tool calling, $5 minimum prepaid.
2. **Amazon Bedrock only.** IAM role (no key) and the AWS story, but it blocks Phases 2–3 until the account exists.
3. **Local model (Ollama).** Free, but weaker tool calling makes the agent flaky and muddies the evaluation. Cannot run on Render.
4. **Provider-agnostic hybrid.** Develop on whichever provider is cheapest to iterate on, choose the evaluation/demo model by a measured bake-off, and deploy on Bedrock once AWS is live.

## Decision

Option 4.

- **Configuration only.** Provider and model ID come from configuration (Strands model providers). There are no provider-specific calls in application code.
- **Development iteration:** Gemini API free tier. All data is synthetic and sandbox-only, with no personal data, so free-tier data handling is acceptable.
- **Model bake-off (Phase 2, ~3 h, < ~$2 in tokens).**
  - Candidates: Gemini 2.5 Flash-Lite, OpenAI GPT-5.4 nano, Anthropic Claude Haiku 4.5. Step up one size if none passes.
  - Tasks: 20, each run 3 times per model — 10 NL→mandate parsing tasks and 10 agent tool-calling tasks against mock PayPal tools, some with hidden-instruction pages.
  - Metrics: schema-valid rate, field accuracy, correct tool and arguments, raw injection susceptibility, consistency across repeats, p50/p95 latency, cost per task.
  - **Pre-registered selection rule:** the cheapest model with ≥ 95% schema-valid output and ≥ 90% correct tool calls; if tied, the lower p95 latency wins.
  - The bake-off code becomes the first version of the evaluation harness.
- **AWS deployment (after the 30 Oct gate):** Bedrock, using the selected model if Bedrock offers it, otherwise the closest Bedrock equivalent, re-checked on the same tasks. Authenticated via IAM role. Budget alarm set first; a Budget *action* is needed for a hard stop.
- **Access route:** direct vendor accounts, not a gateway (OpenRouter was considered: ~$5.80 total, one key, but it adds a hop that distorts latency and an extra data processor). Direct access matches common production practice and gives honest latency numbers.
- **Spend caps:** prepaid credits only, auto-reload off. $5 Anthropic + $5 OpenAI (both vendors' minimum); Gemini on the free tier. Bought only when the Phase 2 bake-off starts.
- **Hosted demo runs to 15 Dec:** the rules require free judge access until the judging period ends (15 Dec 2026). The hosted demo defaults to the scripted agent, and the live-LLM path is rate-limited, so the bake-off credits are not drained.
- **CI:** recorded LLM fixtures. No keys, no cost, deterministic.
- **Keyless local runs:** a scripted (no-LLM) agent replays the attack suite. Ollama is documented as optional and *unvalidated*; no evaluation numbers come from it.
- **Evaluation:** every result records provider, model ID and date. Guard-level baselines run on recorded agent requests without an LLM.

## Design rule recorded with this ADR

AI components may only **add** friction: approve → step-up → block. They never remove it.

- Deterministic rules set the base decision; an AI signal can only escalate it.
- An AI timeout or error never results in approval when the detector is required. Fail-safe = ask the human.

## Consequences

- **Positive:**
  - Unblocks the build today at $0.
  - The model choice is evidence-based and reproducible.
  - Portability across three vendors is demonstrated.
  - The AWS story lands at deployment without being on the critical path.
- **Negative:**
  - Up to two long-lived API keys exist during development; they are kept out of the repo and logs and rotated.
  - Free-tier rate limits may slow bake-off runs.
  - Results are comparable only within one model.
- **If AWS slips past 30 Oct:** the hosted demo uses the bake-off winner via its direct API. Nothing else changes.

## To verify

- **T13:** current prices on each provider's official pricing page.
- **T14:** Anthropic and OpenAI billing availability for a Zambian account. (OpenAI minimum confirmed at $5 on its help centre.)
- **T15:** whether new AWS accounts get free-tier credits applicable to Bedrock.
- **T16:** Gemini free-tier data-use terms and rate limits.
- **T17:** whether Strands' Gemini and OpenAI providers support the tool calling we need.

## Amendment, 8 Nov 2026: model availability and budget
- `gemini-2.5-flash-lite` now returns 404 "no longer available to new users" (live check, 8 Nov). The default
  becomes **`gemini-3.5-flash-lite`**, the current lite model the key can access. Model ID stays configurable
  (`GEMINI_MODEL`).
- No budget for prepaid OpenAI/Anthropic credits: the three-vendor bake-off is reduced to the free routes (Gemini via
  AI Studio; optionally an OpenAI model via GitHub Models if time allows). Recorded here before any bake-off run, so
  the selection rule (cheapest with >= 95% schema-valid output) is unchanged and applied only to models actually tested.

## Amendment, 8 Nov 2026: the AI check runs before PayPal (decision D12, approved by Aaron)
- **Change:** the original design kept hosted LLM calls out of the guard's decision path (p95 < 300 ms). Measured on
  held-out look #2, the AI intent check takes p50 1,090 ms / p95 1,741 ms. Following the pre-registered fallback would
  run it only on payments already held, so normal-looking carts (where "wrong item, right category" hides) would skip it.
- **Decision:** keep the AI check **before** authorisation for every payment the rules haven't already blocked.
- **Why:** blocking before money moves is the product's point; agent checkouts aren't a human waiting at a button;
  PayPal's own calls take 1–4 s (measured), so ~1 s more is the same order. The rules + detector path stays < 1 ms.
- **Reported openly:** the 300 ms mark is met by the deterministic guard and **not** by the AI path; both numbers are
  published. This is a deviation from the pre-registered fallback, recorded here before any further held-out look.
- **Safety unchanged:** AI timeout (15 s) or error → ask the buyer; AI can only escalate.

## Amendment, 9 Nov 2026: the bake-off was not run (docs honesty, review J2)
- **What happened:** the three-vendor bake-off above was **not run**. Prepaid Anthropic and OpenAI credits could not be
  bought in time (T14 still open), and no other model was tested on the bake-off tasks. Bedrock moved after submission
  (ADR-0008 amendment, 7 Nov).
- **How the model was actually chosen: by constraint, not by measurement.** `gemini-3.5-flash-lite` is the only model on
  the free route this project can use (`gemini-2.5-flash-lite` returns 404 for new users, amendment above), and decision
  D14 (Aaron, 8 Nov) rules out a paid tier. No claim is made that it is the best or cheapest of the candidates.
- **How it was then tested:** on the frozen sets, with every number in `docs/evaluation-plan.md` s.8 — catalogue v2
  (27/28 caught, 0/54 false blocks), catalogue v3 (71/75 caught, 0 severe misses, 0/42 false blocks, schema-valid
  99.1%) and held-out looks #2 and #3. The pre-registered schema-valid mark (>= 95%) is met on the model we use. The
  bake-off's tool-calling metric (>= 90% correct tool calls) was **not measured**, because no LLM agent existed until
  the MCP agent (ADR-0005 amendment).
- **What changes in the claims:** README, Devpost and the video say "tested with `gemini-3.5-flash-lite`"; they never
  say "selected by bake-off" or compare vendors. Provider portability stays a design property (model ID from config),
  not a measured result.
- **If keys arrive by Wed 11 Nov:** a small bake-off on the same frozen v3 set, same selection rule, recorded here
  **before** it runs. Otherwise it is roadmap.
