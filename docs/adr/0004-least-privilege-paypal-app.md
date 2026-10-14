# ADR-0004: Least-privilege PayPal sandbox app

- **Status:** Accepted · **Date:** 14 Oct 2026

## Decision
The `agentguard-sandbox` REST app (US merchant sandbox account) enables only: Expanded Checkout (cards), Save payment
methods (Vault), JavaScript SDK v6 (Mobile SDK is bundled), Customer disputes, Transaction search.
Disabled: Payouts, Subscriptions, Invoicing, Payment links, Apple/Google Pay, Fastlane, Log in with PayPal.

## Why
If credentials leak, damage is limited to what the app can do — AgentGuard's app can never send payouts.
US sandbox accounts are used because Vault (Payment Method Tokens v3) is US-only.

## Consequences
- ➖ A feature needed later must be re-enabled deliberately (and recorded here).
