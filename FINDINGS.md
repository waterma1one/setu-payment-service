# Code Review Findings

Reviewed against: original assignment, architecture plan PDF, and full codebase audit.
Date: 2026-04-22

---

## SEVERITY 1 — Submission-Blocking

### F-01 `railway.json` missing migration step
**File:** `railway.json:4`
**Issue:** `startCommand` is just `uvicorn`. No `alembic upgrade head`. Railway deploy will fail
immediately with `relation "events" does not exist` on any DB request.
**Fix:** Prepend `alembic upgrade head &&` to the start command.

### F-02 README deployment URL is a literal placeholder
**File:** `README.md:67`
**Issue:** `Public demo URL: ADD_RAILWAY_URL_HERE`. Assignment says placeholder deployments are
treated as incomplete. This is the first thing reviewers check.
**Fix:** Deploy to Railway and replace the placeholder with the real URL.

### F-03 No screen recording
**Issue:** Assignment requires a screen recording (YouTube/Loom/Google Drive) of all API
walkthroughs. No reference to one anywhere in the repo.
**Fix:** Record a demo video and add the link to README.

### F-04 No AI tool disclosure
**Issue:** Assignment states "if you use AI tools, please disclose which tools you used and how."
Completely absent from the README.
**Fix:** Add a short AI Tools section to the README.

---

## SEVERITY 2 — Functional Correctness Bugs

### F-05 `docker-compose up` has a DB readiness race condition
**File:** `docker-compose.yml:16`
**Issue:** `depends_on: db` only waits for the container to start, not for Postgres to accept
connections. The `api` service immediately runs `alembic upgrade head`, which fails if Postgres
is still initializing (~40% of the time on first run).
**Fix:** Add a `healthcheck` to the `db` service and `condition: service_healthy` to the `api`
dependency.

### F-06 Amount silently overwritten on every event
**File:** `app/services/event_ingestion.py:150`
**Issue:** `transaction.amount = payload.amount` — every event overwrites the stored amount
unconditionally. A corrupted or replayed event with a different amount silently mutates the
financial record.
**Fix:** Only set `amount` when creating the shell (first event). On subsequent events, skip or
validate that it matches.

---

## SEVERITY 3 — Feature Gaps vs Plan and Assignment

### F-07 Reconciliation summary missing per-status counts, avg_amount, discrepancy_count
**File:** `app/services/reconciliation.py:170-183`
**Issue:** The plan (PDF page 5) listed `FILTER(WHERE)` aggregations as a key differentiator.
The actual query returns only `transaction_count` and `total_amount`. Missing:
- `initiated_count`, `processed_count`, `settled_count`, `failed_count`
- `discrepancy_count`
- `avg_amount`
**Fix:** Add conditional aggregates using SQLAlchemy `case()` (cross-DB compatible; equivalent
to `FILTER(WHERE)` on Postgres).

### F-08 Discrepancy response missing `summary.by_type` breakdown
**File:** `app/services/reconciliation.py`, `app/schemas.py`
**Issue:** The plan (PDF page 6) specified a `summary: { total, by_type: {...} }` in the
discrepancy response. Without it, ops teams cannot see type distribution without paginating
through every discrepancy.
**Fix:** Add a `DiscrepancySummary` schema and a second aggregation query in `discrepancy_report`.

### F-09 No future timestamp validation
**File:** `app/schemas.py`
**Issue:** The plan explicitly called out "timestamp not in future" as a required validation.
An event with `timestamp: 2099-01-01` is accepted and stored.
**Fix:** Add a `field_validator` on `timestamp` that rejects datetimes in the future.

### F-10 Postman `baseUrl` hardcoded to `localhost:8000`
**File:** `POSTMAN_COLLECTION.json:10`
**Issue:** Reviewer must manually change the base URL to the deployed endpoint. Should be the
Railway URL once deployed.
**Fix:** Update `baseUrl` variable value to the deployed Railway URL.

### F-11 Postman collection missing filter/sorting examples
**File:** `POSTMAN_COLLECTION.json`
**Issue:** Only one request per endpoint with no filter params. Reviewers cannot exercise
`?status=failed`, `?merchant_id=merchant_1`, date ranges, or `group_by=date` / `group_by=status`
without constructing requests manually.
**Fix:** Add variant requests covering key query param combinations.

---

## SEVERITY 4 — Code Quality Issues

### F-12 Dockerfile installs dev dependencies in production image
**File:** `Dockerfile:12`
**Issue:** `pip install -e ".[dev]"` installs `httpx`, `pytest`, `aiosqlite` into production.
**Fix:** Use `pip install -e "."` without `[dev]` in production Dockerfile.

### F-13 Redundant dead code in settled_after_failure path
**File:** `app/services/event_ingestion.py:180-188`
**Issue:** The special-case `if payment==FAILED and settlement==SETTLED and event_type==SETTLED`
branch sets `SETTLED_AFTER_FAILURE`. But `recompute_discrepancy()` in the else-branch returns
the exact same value for that state. The if-branch is dead code.
**Fix:** Remove the special-case block; let `recompute_discrepancy` handle it uniformly.

### F-14 Seed script opens a new session per event (10,355 sessions)
**File:** `scripts/seed_sample_data.py:35`
**Issue:** Sequential loop with `async with SessionLocal()` per event = 10,355 connection
acquire/release cycles. Seeding will take 3–8 minutes.
**Fix:** Open one session and reuse it across all events, committing in batches.

### F-15 No CORS middleware
**File:** `app/main.py`
**Issue:** No `CORSMiddleware`. Browser-based Postman or any frontend calling the API will
have preflight requests blocked.
**Fix:** Add `CORSMiddleware` with permissive origins for development.

### F-16 `dependency_overrides.clear()` is too broad in test teardown
**File:** `tests/conftest.py:33`
**Issue:** `.clear()` removes all overrides globally. If tests run in parallel or other
overrides exist, this silently breaks them.
**Fix:** Use `app.dependency_overrides.pop(get_session, None)`.

### F-17 Hardcoded transaction UUIDs in tests
**File:** `tests/test_api.py:58,76`
**Issue:** Tests assert against hardcoded UUIDs from the sample data. If sample data is
regenerated the tests silently break.
**Fix:** Build the scenario from scratch in each test (post the specific events, assert on
the resulting state).

---

## SEVERITY 5 — Documentation Gaps

### F-18 `app/main.py` missing lifespan and logging middleware
**File:** `app/main.py`
**Issue:** The plan stated `main.py` should include "lifespan, CORS, logging middleware".
Only the router include is present.
**Fix:** Add CORS (F-15) and a basic request logging middleware.

### F-19 API.md missing discrepancy response body example
**File:** `API.md`
**Issue:** `GET /reconciliation/discrepancies` response documentation says "Response includes
discrepancy rows with the event timeline attached" with no example JSON. Every other endpoint
has a full example.
**Fix:** Add a full response body example.

### F-20 `MerchantOut` type annotation inconsistency
**File:** `app/schemas.py:78`, `app/services/reconciliation.py:138`
**Issue:** `TransactionDetailsResponse.merchant` is typed as `MerchantOut` in the schema but
`get_transaction_details` returns a plain `dict`. Works only because Pydantic coerces dicts.
**Fix:** Use `MerchantOut(...)` constructor in `get_transaction_details`.

---

## Fix Priority Order

| # | Finding | File | Effort |
|---|---------|------|--------|
| F-01 | railway.json migration | `railway.json` | 2 min |
| F-04 | AI disclosure | `README.md` | 5 min |
| F-05 | Docker DB readiness race | `docker-compose.yml` | 10 min |
| F-09 | Future timestamp validation | `app/schemas.py` | 5 min |
| F-07 | Rich reconciliation summary | `reconciliation.py`, `schemas.py` | 45 min |
| F-08 | Discrepancy by_type summary | `reconciliation.py`, `schemas.py` | 20 min |
| F-06 | Amount overwrite protection | `event_ingestion.py` | 10 min |
| F-13 | Remove dead code | `event_ingestion.py` | 5 min |
| F-15 | CORS middleware | `app/main.py` | 5 min |
| F-12 | Dockerfile dev deps | `Dockerfile` | 2 min |
| F-14 | Seed script session reuse | `scripts/seed_sample_data.py` | 15 min |
| F-16 | conftest override teardown | `tests/conftest.py` | 2 min |
| F-20 | MerchantOut constructor | `reconciliation.py` | 2 min |
| F-11 | Postman filter examples | `POSTMAN_COLLECTION.json` | 15 min |
| F-19 | API.md discrepancy example | `API.md` | 10 min |
| F-17 | Hardcoded test UUIDs | `tests/test_api.py` | 20 min |
| F-18 | Logging middleware | `app/main.py` | 10 min |
