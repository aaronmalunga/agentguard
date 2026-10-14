# ADR-0002: Deploy one artefact to Render (judge demo) and AWS (architecture showcase)

- **Status:** Accepted · **Date:** 14 Oct 2026

## Context
Judges must be able to run or interact with a working build until 15 Dec 2026. PayPal webhooks need a public HTTPS
endpoint. The project is also a portfolio piece for a Solutions Architect career, where AWS matters.

## Options
1. AWS only — strong architecture story; more setup time in the final week; account not yet active.
2. Render only — fastest reliable demo; weaker cloud-architecture story.
3. **Both, one container artefact** — Render for the demo; AWS (Lambda via Lambda Web Adapter, DynamoDB, CDK, SSM,
   X-Ray/OpenTelemetry) as a second target.

## Decision
Option 3. Render is set up first (always-on paid instance only for the judging window, to avoid cold starts).
AWS work starts **only if the core flow works end-to-end by 30 Oct**; otherwise it ships right after submission.
AWS budget alarm (~$10) is created before any other resource. Target total spend ≤ ~$25 (pricing verified before paying).

## Consequences
- ➕ Reliable judge link + AWS portfolio story; no lock-in (build once, deploy many).
- ➖ ~10 extra hours; two configurations (each deployment registers its own webhook URL).
