# From demo to production: known gaps and the v2 plan

AgentGuard is a hackathon build. This page lists what a real deployment would need that the demo does not have, so
nobody has to discover it. Written 10 Nov 2026 from an adversarial review ("what would a technical hiring manager or a
payments engineer pick apart?").

## What is real, what is demo

| Area | Today | What production needs |
|---|---|---|
| Storage | Each demo session is an in-memory SQLite database; a restart or redeploy wipes it | Durable database for payments, the idempotency store and the audit log |
| Where it sits | AgentGuard calls PayPal itself with the sandbox app's credentials (least-privilege app, ADR-0004) | Runs inside the operator's own infrastructure with their PayPal credentials; one deployment per operator or proper tenant isolation |
| Who can call it | Demo bearer tokens; per-agent keys (hashed, revocable) | Separate customer accounts (tenants) and machine-to-machine login |
| Receipt signing key | Held in the app's memory (ADR-0008) | AWS KMS; key rotation |
| Keeping records true | Verified PayPal webhooks, forward-only state machine (ADR-0009) | Also a scheduled reconciliation job against PayPal, because webhooks can be late or lost |
| Evidence | Synthetic attack catalogues; 40 pre-registered real-agent runs | An outside benchmark (licence checked) and an open red-team; real developer feedback |
| Rollout | Enforce (default) or shadow per mandate (ADR-0010: hard limits act, judgement checks only logged) | Shadow → advisory → enforce per check, with false asks measured on real traffic before switching |
| AI provider | One model, chosen by constraint (ADR-0006) | Provider comparison including cost per 1,000 checks; EU-compliant paid tier |

## v2 plan (after judging, in this order)

0. **Design doc first.** One named customer (e.g. an agent platform whose users' agents buy from PayPal merchants),
   with requirements: p95 decision latency, availability, cost per 1,000 checks, EU users, tenants, and what happens
   when PayPal or the model is down. Every later choice traces back to it.
1. **Make it usable:** durable storage, tenants and machine login, KMS signing key, reconciliation job, advisory mode (shadow is built).
2. **AWS because the requirements call for it:** CDK deployment, Bedrock as a second provider, the bake-off with
   cost per 1,000 checks, one trace showing where a decision's time goes.
3. **Outside proof:** external benchmark or open red-team; three developer conversations with a fixed question list.
4. **Package:** case study, evaluation notebook that rebuilds every reported number from `evidence/`, "what I'd do
   differently".

Deferred: PayPal Disputes API submission, Postman collection. Kept because cheap: contract tests from the OpenAPI
spec, a coverage number. Deep operations work (exactly-once execution, tracing) stays out of scope here; it is the
subject of a separate project.
