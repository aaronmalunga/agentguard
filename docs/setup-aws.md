# AWS setup (ADR-0008): do these in order

Region: **Europe (Stockholm) eu-north-1** (top-right region menu in the console). Sign in as the account owner only for
steps 0–2; after that, never use the root user for work.

## 0. MFA on the root user (2 min)
Top-right account name → **Security credentials** → *Multi-factor authentication (MFA)* → **Assign MFA device** →
Authenticator app → scan the QR code with your phone app → type two codes → **Add MFA**.

## 1. Budget alarm FIRST (3 min)
Search bar → **Billing and Cost Management** → left menu **Budgets** → **Create budget** →
*Use a template* → **Monthly cost budget** → Budget name `agentguard-10usd` → Enter budgeted amount **10** →
Email recipients: your email → **Create budget**.
The template adds email alerts automatically (as of writing: actual spend at 85% and 100%, and forecast at 100%). Check the budget shows in the list.

## 2. App user with least privilege (5 min)
Search bar → **IAM** → left menu **Users** → **Create user** → User name `agentguard-app` → leave
"Provide user access to the AWS Management Console" **unticked** → **Next** → *Attach policies directly* → don't tick
anything yet → **Next** → **Create user**.
(We attach a tight policy on Sat, once the KMS key and S3 bucket exist, so it can name their exact ARNs.)

## 3. Parameter Store: PayPal sandbox keys (5 min)
Search bar → **Systems Manager** → left menu **Parameter Store** (it sits under *Application Management* or *Application Tools*, depending on the console version) → **Create parameter**:
- Name `/agentguard/sandbox/paypal_client_id` · Tier **Standard** · Type **SecureString** · KMS key source *My current
  account* · KMS Key ID `alias/aws/ssm` · Value: your sandbox client ID → **Create parameter**.
- Repeat with Name `/agentguard/sandbox/paypal_client_secret` and the sandbox secret.
- Repeat with Name `/agentguard/sandbox/paypal_env` · Type **String** · Value `sandbox`.

Tell Claude when 0–3 are done. Don't paste keys into the chat.

## Later (Claude prepares the exact steps on the day)
- Sat 7 Nov: KMS signing key, S3 bucket with Object Lock, then the IAM policy and an access key for Render.
- Mon 9 Nov: Bedrock model access for the bake-off.
