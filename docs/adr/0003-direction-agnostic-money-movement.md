# ADR-0003: Model every agent action as a money-movement request

- **Status:** Accepted · **Date:** 14 Oct 2026

## Context
Agents now sit on both sides of a transaction: a buyer's shopping agent spends money; a merchant's support agent issues
refunds. Unit 42 documents attacks in both directions ([S3](../sources.md#s3)).

## Decision
The core abstraction is a **money-movement request**: requesting agent, direction (buyer→merchant purchase or
merchant→buyer refund), amount, line items, and the governing mandate/policy. One pipeline (rules → AI checks →
decision → audit) handles every direction. Build order: purchases (core), then refunds (first stretch item).

## Consequences
- ➕ Refund guard becomes new rules + one PayPal call, not a new system (open/closed principle).
- ➖ Slightly more abstract data model up front.
