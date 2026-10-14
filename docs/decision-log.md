# Decision log

Every significant decision, pivot and correction, newest first. Real architectural decisions also get an
[ADR](adr/). Format: **date — decision** · why · what changed.

## 14 Oct 2026 — Project start (Stage 0)

- **Agent framework: Strands Agents for the demo agent; guard framework-free** → [ADR-0005](adr/0005-agent-framework-strands.md).
  *Why:* trust boundary (agent asks, guard moves money); MCP built in; Apache-2.0; Bedrock-ready.
- **Two decision points instead of one** → [ADR-0001](adr/0001-two-decision-points.md).
  Clear violations are blocked *before* authorization; only uncertain cases are authorized and held for a human.
  *Why:* PayPal's data ([S5](sources.md#s5)) shows the benefit of fraud prevention comes from stopping it upstream; an
  authorization already reaches the issuer and holds buyer funds. *Changed:* the brief's single "authorize → guard →
  capture/void" flow.
- **Dropped the original pitch hook.** The quote "PayPal does not assess AI intent or behavior" could not be found at
  its cited source. *Replaced by* PayPal's own merchant research ([S1](sources.md#s1)): liability for disputed agent
  purchases is "in flux". *Why:* every pitch claim must be verifiable.
- **Wording correction:** PayPal's AP2 post says mandates *could* feed fraud models and dispute evidence — stated as
  possibility, not a deployed feature ([S2](sources.md#s2)).
- **Unit 42 corrections:** "fake merchants" is not a separate scenario in the article; line-item display and
  shipping-scan checks are our inference ([S3](sources.md#s3)).
- **Direction-agnostic guard** → [ADR-0003](adr/0003-direction-agnostic-money-movement.md). One pipeline for any agent
  money movement: buyer purchases first (core), merchant refunds next (stretch).
- **Deployment: Render + AWS** → [ADR-0002](adr/0002-deployment-render-and-aws.md). Render hosts the always-on judge
  demo; AWS serverless is the architecture showcase, gated on the 30 Oct core-flow checkpoint.
- **Least-privilege sandbox app** → [ADR-0004](adr/0004-least-privilege-paypal-app.md). Only the PayPal features we use
  are enabled; Payouts is off.
- **Stage 0 spike passed** ([evidence](../spike/)): authorize/capture/void, idempotent capture, Vault charge with no
  cardholder present, and a decline that returns HTTP 201 with authorization `DENIED` → the guard must check payment
  status, never only the HTTP code.
- **CI blocked by GitHub account billing lock** (job never started; not a code failure). Until resolved, CI steps are
  replayed locally before each push. Workflow runner pinned to `ubuntu-24.04` for reproducibility.
- **Spike bug fixed:** a logging parameter named `status` collided with the payment `status` field. Lesson: name values
  by meaning (`http_status` vs payment status); covered by unit tests from Phase 1.

## Before 14 Oct (from planning)
- Name **"AgentGuard — built on PayPal"** (never "PayPal AgentGuard"), licence **Apache-2.0**, **sandbox only**,
  fresh repository with no reused course code.
