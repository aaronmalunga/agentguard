# ADR-0008: Pull selected AWS services into the sprint (revises ADR-0002's gate)

- **Status:** Accepted · **Date:** 5 Nov 2026
- **Deciders:** Aaron (decision), Claude (options and analysis)
- **Related:** ADR-0002 (Render + AWS; AWS gated on a 30 Oct core-flow checkpoint), ADR-0006 (LLM bake-off)

## Context
ADR-0002 put all AWS work after a 30 Oct checkpoint. The schedule moved (sprint is now 5–12 Nov), so that gate no
longer fits. Some AWS services do a real job in AgentGuard *now*, are cheap, and are core Solutions Architect skills.
Account: AWS Free plan, $100 credit, region **eu-north-1 (Stockholm)**, no card on file, credit valid to 15 Apr 2027.

## Options
1. Keep ADR-0002 as is: no AWS until after submission.
2. **Pull in a few services that each do a real job**; keep the full serverless showcase for after submission.
3. Move the whole demo to AWS now (Lambda, DynamoDB, CDK): too much new infrastructure in an 8-day sprint.

## Decision
**Option 2.** Render stays the always-on judge demo. In the sprint:

| Service | Job in AgentGuard | Order |
|---|---|---|
| **AWS Budgets** | Email alarm at $10 (and at 50% / 80%) | **First, before anything else exists** |
| **IAM** | One app user with a policy that allows only the actions below, on only our resources | 2 |
| **SSM Parameter Store** (SecureString) | PayPal sandbox keys and config, instead of plain env vars | 3 |
| **AWS KMS** (asymmetric signing key) | Signs every Receipt of Intent (N1). The private key never leaves KMS; anyone can verify with the public key | Sat 7 Nov |
| **S3 + Object Lock** | Write-once archive of receipts and audit exports; Parquet evaluation data | Sat 7 Nov |
| **Amazon Bedrock** | One candidate in the LLM bake-off (ADR-0006) | Mon 9 Nov |

After submission (unchanged from ADR-0002): Lambda (Web Adapter), DynamoDB, EventBridge Scheduler (auto-void),
CloudWatch/X-Ray via ADOT, Athena, CDK.

**Rules**
- Budget alarm first. Spend target < $10 of the credit to 15 Dec.
- The app's AWS access key is the only long-lived AWS secret. It lives in Render's secret env vars, never in git, logs or
  screenshots. Its policy is scoped to one KMS key ARN, one S3 bucket and one Parameter Store path.
- The root account is never used for work; it gets MFA.
- **Fallback:** if KMS or S3 isn't ready on Sat, receipts are signed with a local Ed25519 key in Parameter Store, and the
  README says so. The signing interface stays the same, so swapping in KMS is a config change.

## Consequences
- **Positive:** real security jobs (key custody, immutable evidence, secrets management, cost control); AWS skills on
  the resume; Bedrock adds a fourth model family to the bake-off without another vendor key.
- **Negative:** more setup on Days 1–3; an AWS key to protect; Render → AWS calls add latency to receipt signing
  (measured, not assumed, and kept off the pre-authorisation path).

## To verify (before use)
- Which KMS key specs exist in eu-north-1 and whether one maps to a JWS algorithm we can verify in browsers
  (ECC_NIST_P256 → `ES256` is the safe default; check whether an Ed25519 spec is offered).
- Bedrock model availability in eu-north-1 (or cross-region inference) on the Free plan, and model access approval.
- Object Lock must be enabled when the bucket is created; choose governance mode (deletable by an admin) for the demo,
  so the bucket can be cleaned up after judging.
- Current prices for KMS keys, requests and S3.
