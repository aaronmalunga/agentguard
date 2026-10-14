# ADR-0001: Two decision points — before authorization and before capture

- **Status:** Accepted · **Date:** 14 Oct 2026

## Context
PayPal lets a merchant *authorize* a payment (reserve funds) and later *capture* (take) or *void* (release) it — proven
in our sandbox spike. The first plan was: authorize every agent purchase, let the guard decide, then capture or void.
But an authorization already reaches the card issuer and holds the buyer's funds. PayPal's own data ([S5](../sources.md#s5))
links stopping fraud *before* authorization to fewer issuer declines and better approval rates over time.

## Decision
1. **Pre-authorization:** deterministic rules, injection detection and cart-vs-mandate checks run first. Clear
   violations are **blocked; nothing is sent to PayPal.**
2. **Pre-capture:** cases that need judgement are **authorized and held**; a human approves (capture) or rejects (void).
   Approved low-risk purchases are captured automatically.

## Consequences
- ➕ Blocked attacks never reach the issuer; no buyer funds held for them.
- ➕ The authorization hold gives a safe window for human review.
- ➖ Two code paths to test; authorizations expire if not captured in time (honor period to be verified — T9).
- Open: whether a voided authorization affects the merchant's issuer profile (T12).
