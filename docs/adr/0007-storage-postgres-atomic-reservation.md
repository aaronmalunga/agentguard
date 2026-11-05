# ADR-0007: Storage: PostgreSQL with an atomic budget reservation

- **Status:** Accepted · **Date:** 5 Nov 2026
- **Deciders:** Aaron (decision), Claude (options and analysis)
- **Related:** ADR-0001 (two decision points), ADR-0002 (Render + AWS), requirement R13 (atomic budget reservation)

## Context
A mandate has a budget ("max $60"). An agent can send several payment requests at the same moment, by mistake or
because it was tricked into splitting one big purchase into small ones. If two requests each read "$40 left" and both
pass, the buyer is charged $80 against a $60 mandate. This is the classic **check-then-act race**.

Money also stays "in flight" for a while: an authorisation can be held for up to 29 days (measured, spike v2) before it
is captured or voided. So the budget needs three numbers, not one: **spent** (captured), **reserved** (authorised and
held), and the **limit**.

We also need: the decision log (hash-chained, ADR to come), mandates and their versions, and idempotency records.

## Options
1. **SQLite only.** Simplest, zero cost, fine in tests. But one writer at a time, and the Render demo would need a paid
   persistent disk; data is lost on redeploy without it.
2. **PostgreSQL** (SQLAlchemy 2 + Alembic migrations). The industry default; row-level locking and transactional
   `UPDATE ... RETURNING`; hosted cheaply. Adds a service to run.
3. **DynamoDB.** Conditional writes give the same atomic guarantee. Fits the AWS showcase (ADR-0002), but slows the
   sprint and doesn't run in local tests without an emulator.

## Decision
**Option 2, PostgreSQL, with SQLite for unit tests.** The reservation is **one conditional statement**, so no read is
ever separated from its write:

```sql
UPDATE mandate_budget
   SET reserved = reserved + :amount
 WHERE mandate_id = :mandate_id
   AND spent + reserved + :amount <= budget_limit
RETURNING spent, reserved, budget_limit;
```

- No row returned ⇒ over budget ⇒ **block before authorisation** (ADR-0001), and PayPal is never called.
- Capture: `reserved -= amount, spent += amount` in one statement. Void, decline or expiry: `reserved -= amount`.
- If PayPal fails after reserving, the reservation is released; if the outcome is unknown (network error), it stays
  reserved until the authorisation is read back. **Never** release on an unknown outcome.
- The same SQL runs on SQLite 3.35+ (supports `RETURNING`), so unit tests exercise the real statement.
- A concurrency test fires N parallel reservations against a real Postgres and checks the total never passes the limit
  (Postgres in CI via a service container; locally via Docker).
- Money is stored as integer **cents**, never floats.
- Hosting: a free serverless Postgres (e.g. Neon) or Render Postgres (paid). Render's free Postgres expires after 30 days,
  before judging ends on 15 Dec, so it's ruled out. Final choice when we deploy (Sun 8 Nov), after checking current
  terms and prices.

## Consequences
- **Positive:** a race-free budget that's easy to explain in an interview; the same pattern maps to DynamoDB
  conditional writes for the AWS version (ADR-0002); migrations make schema changes reviewable.
- **Negative:** one more service to run and monitor; free tiers can pause (cold start), so the judge demo must keep it
  warm or use a paid tier during judging.
- **To verify:** Neon free-tier limits and pause behaviour; Render Postgres price; SQLite version on the CI runner.
