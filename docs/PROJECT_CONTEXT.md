# Project context: everything a new contributor (or assistant) needs

**AgentGuard, built on PayPal.** Entry to the PayPal AI Hackathon 2026 (deadline 12 Nov 2026) and a portfolio
project. Owner: Aaron Malunga. Built with Claude (Anthropic) as an AI pair; all design decisions approved by Aaron.

## The problem
AI agents can now pay for people. A payment can be *authorised* (the agent had permission) without being *intended*
(the buyer never wanted it). PayPal's merchant research says liability for disputed agent purchases is "in flux"
(`docs/sources.md` S1). AgentGuard checks intent before money moves and keeps evidence for disputes.

## How it works
1. The buyer writes rules in plain English → the AI drafts a **mandate** (budget, item limits, shops, categories,
   dates) → the buyer approves it. Mandates are immutable and versioned; their fingerprint goes into the PayPal order's
   `custom_id`.
2. The agent asks to pay → **rules** check every hard limit → a local **detector** looks for hidden instructions in
   the shop page → the **AI** checks the cart's meaning against the buyer's words.
3. Outcome: **approve** (authorise + capture) · **hold** (authorise, buyer approves → capture, rejects → void, $0) ·
   **ask first** (nothing sent to PayPal until the buyer says yes) · **block** (PayPal never called).

## Decision index
| Topic | Where |
|---|---|
| Two decision points (block before authorising; hold before capturing) | ADR-0001 |
| Hosting: Render demo; AWS after submission | ADR-0002, ADR-0008 (+ amendment) |
| One money-movement model (purchases now, refunds later) | ADR-0003 |
| Least-privilege PayPal app | ADR-0004 |
| Guard framework-free; agent separate | ADR-0005 |
| LLM: provider-agnostic, Gemini, AI before PayPal (D12) | ADR-0006 (+ amendments) |
| Storage: race-free budget reservation | ADR-0007 |
| Two kinds of "ask"; never trust the agent; buyer approval via PayPal; page capture by proxy (D1–D4) | `review-2026-11-05.md` |
| Every other dated decision | `decision-log.md` |

## Evidence trail
- `docs/evaluation-plan.md`: what we measure, pass marks, every change after freezing (§8, newest first).
- `docs/ai-governance.md`: guardrails, hallucination controls, results, gaps (model card).
- `docs/ai-integration-log.md`: first live AI integration, every error and fix.
- `docs/review-*.md`, `docs/review-process.md`: adversarial reviews.
- `docs/paypal-feedback.md`: PayPal developer friction log.
- `evidence/runs/*.json`: raw results of every evaluation; `spike/results/*.json`: live sandbox runs.

## Status (8 Nov 2026)
Done: PayPal gateway (live 9/9), full flow (live 6/6), rules, detector, AI layer (live), race-free budget, evaluation
(v0/v1 dev + 3 held-out looks planned/done, v2, v3 pending). Next: web app (buyer, shop + agent, AG Grid console),
hosting on Render, receipts and audit hash chain, README, video. Known gaps: `docs/ai-governance.md` §6.
