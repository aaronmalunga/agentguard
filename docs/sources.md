# Evidence & sources

Every external claim AgentGuard makes is listed here with its publisher, date, link, what we use it for and its limits.
Our own conclusions are labelled **inference**. Last checked: 14 Oct 2026.

<a id="s1"></a>
## S1 — PayPal: "How Merchants Are Preparing for Agentic Commerce"
- **Publisher / date:** PayPal Business Resource Center (Laura Gower), 27 Apr 2026
- **Link:** https://www.paypal.com/us/brc/article/agentic-commerce-pulse-report-findings
- **Based on:** PayPal Agentic Commerce Pulse Report — online survey of 498 US merchants, 23 Feb – 3 Mar 2026, plus 7 interviews ([full report PDF](https://www.paypalobjects.com/marketing/GCI_Q1_26_PayPal_Agentic_Pulse_Final_Report.pdf))
- **We use:** "If an AI agent makes a purchase that a customer disputes, who bears responsibility?" — "there's no clear consensus"; "liability is in flux"; nearly two-thirds of merchants want a standardized liability framework; merchants want providers to "extend fraud protection and buyer/seller coverage to agent-initiated purchases"; merchants keep a human in the review loop.
- **Limits:** merchants only (no consumer data); US only.

<a id="s2"></a>
## S2 — PayPal Developer blog: Agent Payments Protocol (AP2)
- **Date:** 16 Sep 2025 · **Link:** https://developer.paypal.com/community/blog/PayPal-Agent-Payments-Protocol/
- **We use:** Cart (human-present), Intent (human-not-present) and Payment mandates; mandate data *could* feed fraud models and *could* add cryptographic artifacts to dispute evidence.
- **Limits:** stated as possibilities ("could"), not deployed features. AgentGuard implements AP2-*style* mandates, not the AP2 protocol.

<a id="s3"></a>
## S3 — Unit 42 (Palo Alto Networks): "Who's Really Shopping? Retail Fraud in the Age of Agentic AI"
- **Date:** 20 Mar 2026 · **Link:** https://unit42.paloaltonetworks.com/retail-fraud-agentic-ai/
- **We use:** gift-card theft via hidden instructions added to a cart mandate; returns fraud via hidden instructions and a fake tracking ID; friendly fraud amplified by bot-driven refunds. Basis of our attack suite.
- **Limits / inference:** "show every line item" and "require a real shipping scan before refunds" are our reading of the article's implications, not its explicit recommendations.

<a id="s4"></a>
## S4 — PayPal: "What Does Dispute Transaction Mean? A Complete Merchant Guide"
- **Date:** 17 Jul 2026 (PayPal Editorial Staff)
- **We use:** sellers have 10 days to respond to a claim; resolution usually ~30 days; funds may be held; high claim/chargeback rates can lead to reviews, holds, reserves or limitations; chargebacks often incur fees; friendly fraud = "reporting an authorized charge as unauthorized"; evidence includes "customer communications showing prior agreement or confirmation".
- **Inference:** an agent buying a correctly described, correctly priced item through an authorized payment fits no standard dispute reason cleanly; a signed mandate is the agent-era form of "prior agreement or confirmation".
- **Limits:** no fee amounts given.

<a id="s5"></a>
## S5 — PayPal: "Auth rate increases with merchants using a fraud protection solution"
- **Date:** 9 Mar 2026 (PayPal Editorial Staff)
- **We use:** stopping fraud before authorization reduces fraud-driven issuer declines and can improve approval rates over time; PayPal sample (Fraud Protection Advanced, 2024): 58% of merchants reduced issuer declines within 3 months, 76% of those also improved authorization rates.
- **Limits:** before/after comparison on a PayPal sample (size not stated); gradual effect; measures a different PayPal product — applying it to AgentGuard is **inference**. Drives [ADR-0001](adr/0001-two-decision-points.md).

<a id="s6"></a>
## S6 — PayPal: "How to protect your business when taking online payments"
- **Date:** 26 Apr 2024 · **Link:** https://www.paypal.com/us/brc/article/seller-protection-agentic-commerce
- **We use:** chargebacks initiated by scammers are costly and documentation-heavy for small businesses.

## S7 — Devpost: PayPal AI Hackathon Official Rules
- **Read:** 10 Nov 2026, https://paypalaihackathon.devpost.com/rules
- **What binds us:** third-party APIs and data must be used under their own terms (s4 "Third Party Integrations");
  video on YouTube, publicly visible, under 3 minutes, no third-party trademarks or copyrighted music without
  permission; hosted demo free and unrestricted until the Judging Period ends (15 Dec 2026, 08:00 PT); **no
  changes to the submission after the deadline** (s5), except removals Devpost permits for infringing or personal
  material; ambiguous terms need a written request for clarification (s11).
- **Devpost answers (Discord, 9–10 Nov, USER-REPORTED, screenshots kept by Aaron):** product names and photos
  returned by a sponsor's API may appear in the video as they appear in the app, if that use follows the sponsor's
  terms (keep the focus on the app, no logo close-ups, no implied endorsement); repo and hosted demo stay frozen at
  the deadline, further work only on a separate branch.

## S8 — Google: Gemini API Additional Terms of Service
- **Read:** 10 Nov 2026 (effective 23 Mar 2026), https://ai.google.dev/gemini-api/terms
- **What binds us:** "You may use only Paid Services when making API Clients available to users in the European
  Economic Area, Switzerland, or the United Kingdom." Unpaid use may be reviewed by people and used to improve
  Google's products, so only synthetic data is ever sent (already the rule). The $300 Google Cloud trial credit
  does not cover the Gemini API (Google Cloud free-trial docs, read 10 Nov).
- **Consequence:** the public demo either runs on a paid Gemini project or does not call Gemini live for visitors;
  decision recorded in `docs/decision-log.md` (10 Nov).

## S9 — Channel3: Publisher Terms and caching guide
- **Read:** 10 Nov 2026 (Publisher Terms effective 2 Nov 2026), https://trychannel3.com/terms/publishers ;
  https://docs.trychannel3.com/guides/caching.md
- **What binds us:** showing Channel3 output to users of our app is allowed (s4–s5); we must not cache, store or
  redistribute a *significant portion* of the catalogue, train models on it, give anyone our key, or **publish
  benchmark or evaluation results of the service without written consent** (s7); users must be bound to terms
  protecting Channel3's data (s5). Caching guide: cache product IDs, refresh prices and details at display time.
- **What we do:** 5 products stored (IDs + titles + image links + our demo prices); market price fetched live per
  decision; no Channel3 timings published (removed from the API, docs and smoke files on 10 Nov); README and app
  carry a "demo only, not for reuse" notice; Channel3 data never used for training or the attack catalogues.
  **Open:** written confirmation from Channel3 that the 5-product snapshot is acceptable (asked in Discord).

## Technical documentation
- PayPal sandbox card testing & rejection triggers — https://developer.paypal.com/tools/sandbox/card-testing/
- PayPal Orders v2 — https://developer.paypal.com/docs/api/orders/v2/
- PayPal Payments v2 (authorize / capture / void / refund) — https://developer.paypal.com/docs/api/payments/v2/
- PayPal Payment Method Tokens v3 (Vault) — https://developer.paypal.com/docs/api/payment-tokens/v3/
- PayPal webhooks — https://developer.paypal.com/api/rest/webhooks/
- PayPal agent toolkit / MCP server — https://github.com/paypal/agent-toolkit
- PayPal AI Hackathon rules — https://paypalaihackathon.devpost.com/rules

## Removed claims
- *"PayPal does not assess AI intent or behavior"* — appeared in early planning notes; could not be found at the cited source on 14 Oct 2026. Not used. See [decision log](decision-log.md).
