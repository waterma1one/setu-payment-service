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
3. Upsert merchant metadata (only update `merchant_name` when it actually changed).
4. Create a transaction shell row if one does not exist (`INSERT ... ON CONFLICT DO NOTHING` on Postgres).
5. Lock the transaction row with `SELECT ... FOR UPDATE`.
6. Apply state transition rules.
7. Recompute or preserve discrepancy state.
8. Flush and commit.

If `event_id` already exists, the inner transaction rolls back and the API returns a duplicate response. The duplicate path also compares the re-submitted payload against the stored event: if any field differs (amount, timestamp, event_type, etc.) the response is `ingestion_status="duplicate_with_conflict"` and a warning is logged.

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

### Design Choices (explicit)
- **`processed_not_settled` is a point-in-time flag.** Any transaction currently in `(processed, pending)` is flagged. It clears automatically when a settlement event arrives. The service does not apply a stale-threshold; callers who want a "stale only" view can filter the discrepancy list by `last_event_timestamp` or `updated_at` on the client side. This keeps the server stateless with respect to clock progression — no background job is needed to re-lift the flag as time passes.
- **`conflicting_state_transition` is sticky.** Once a non-duplicate event has contradicted the lifecycle, the transaction is flagged permanently, even if subsequent events would resolve to a clean end state. The rationale: contradictory events mean upstream state is ambiguous, and silently erasing that signal would hide the original reconciliation evidence. The other two discrepancy types are auto-clearable because they describe the *current* state; this one describes a *historical event of suspicion*.
- **`created_at` is the earliest observed `event_timestamp`, not the insertion time.** When a late-arriving event has a timestamp earlier than the current `created_at`, we pull `created_at` back (`min(current, new)`). Tradeoff: date-range filters reflect business-time, not wall-clock insertion order. `updated_at` (wall-clock) and `last_event_timestamp` (business-time of latest event) are kept separately so every time dimension is preserved.
- **Amount is immutable after initiation.** A later event with a different amount for the same `transaction_id` is silently ignored for the amount field (event row still stored). This prevents corrupted upstream replays from mutating financial data.

## Concurrency
- Postgres is the primary runtime because concurrent ingestion matters.
- The implementation first ensures the transaction shell exists (via `ON CONFLICT DO NOTHING`), then acquires a row lock before applying state transitions.
- The FK from `events.transaction_id` to `transactions.transaction_id` is `DEFERRABLE INITIALLY DEFERRED` so the events insert and the shell-row insert can live in the same DB transaction without ordering constraints. The FK is still enforced at commit.
- `tests/test_concurrency.py` contains an opt-in Postgres-only test (`SETU_TEST_POSTGRES_URL`) for the first-write race.

## Indexing
- `events(transaction_id, event_timestamp desc)` — powers the event timeline subquery in `/reconciliation/discrepancies` and `/transactions/{id}`.
- `transactions(merchant_id, created_at desc)` — `merchant_id` filter + default sort.
- `transactions(payment_status, settlement_status, created_at desc)` — enables index-only filtering when `status` is translated to its underlying column predicates (see `_STATUS_FILTERS` in `services/reconciliation.py`).
- `transactions(created_at desc)` — bare-listing fallback.
- Partial discrepancy index on Postgres: `WHERE discrepancy_type IS NOT NULL` — ~8× smaller than a full column index given the data distribution (~475/3800 rows are discrepant).

## Deployment
- Railway is the primary hosted target.
- Startup runs `alembic upgrade head` before the ASGI server.
- Seeding is an explicit one-time command, not an automatic boot behavior.
- Docker image runs as a non-root user and uses a layered install so dependency installs are cached across source changes.
