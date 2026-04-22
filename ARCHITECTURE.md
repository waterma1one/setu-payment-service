# Architecture

## Overview
The service uses an append-only `events` table plus a `transactions` read model. This keeps ingestion auditable while making list, detail, and reconciliation queries cheap and explicit.

## Core Tables
- `merchants`
  - partner metadata keyed by `merchant_id`
- `transactions`
  - current operational state per transaction
  - source-of-truth fields: `payment_status`, `settlement_status`, `discrepancy_type`
- `events`
  - immutable event history keyed by `event_id`

## Why This Shape
- Pure event replay would complicate reviewer-facing query endpoints.
- A read model keeps reconciliation queries in SQL and avoids Python-side state reconstruction for every request.
- Keeping raw events preserves auditability and makes discrepancy investigation possible.

## Ingestion Flow
1. Validate the incoming payload.
2. Add the incoming event to the session.
3. Upsert merchant metadata.
4. Create a transaction shell row if one does not exist.
5. Lock the transaction row with `SELECT ... FOR UPDATE`.
6. Apply state transition rules.
7. Recompute or preserve discrepancy state.
8. Flush and commit.

If `event_id` already exists, the transaction is rolled back and the API returns `ingestion_status="duplicate"` with the current transaction snapshot.

## State Model
- `payment_status`
  - `initiated`
  - `processed`
  - `failed`
- `settlement_status`
  - `pending`
  - `settled`

Derived API `status`:
- `failed`
- `settled`
- `processed_pending_settlement`
- `initiated`

## Discrepancy Rules
- `processed_not_settled`
  - payment processed, settlement still pending
- `settled_after_failure`
  - settlement recorded after failure
- `conflicting_state_transition`
  - a unique non-duplicate event implied a contradictory lifecycle transition

Exact duplicate delivery is not treated as a discrepancy.

## Concurrency
- Postgres is the primary runtime because concurrent ingestion matters.
- The implementation first ensures the transaction shell exists, then acquires a row lock.
- The project includes an opt-in Postgres-only concurrency test for the first-write race.

## Indexing
- `events(transaction_id, event_timestamp)`
- `transactions(merchant_id, created_at desc)`
- `transactions(payment_status, settlement_status, created_at desc)`
- `transactions(created_at desc)`
- partial discrepancy index on Postgres

## Deployment
- Railway is the primary hosted target.
- Startup remains side-effect free.
- Seeding is an explicit one-time command, not an automatic boot behavior.

