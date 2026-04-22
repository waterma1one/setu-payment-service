# setu-payment-service

Reviewer-first backend service for the Setu Solutions Engineer take-home assignment. The service ingests payment lifecycle events, maintains current transaction state, and exposes reconciliation-focused APIs for operations teams.

## Stack
- FastAPI
- PostgreSQL
- SQLAlchemy 2.x (async)
- Alembic
- Railway for primary hosted deployment

## Project Layout
- `app/`: API, models, services, configuration
- `alembic/`: schema migrations
- `scripts/seed_sample_data.py`: explicit sample data seed command
- `data/sample_events.json`: provided dataset (10,355 events, 3,800 transactions, 5 merchants)
- `tests/`: API and concurrency verification
- `ARCHITECTURE.md`: design decisions and state model
- `API.md`: endpoint contract and examples

## Deployment

**Live URL:** https://api-production-e564.up.railway.app

**Demo recording:** `ADD_LOOM_OR_YOUTUBE_URL_HERE`

To deploy on Railway:
1. Create a new Railway project, add a PostgreSQL plugin.
2. Push this repository; Railway uses `railway.json` automatically.
3. `railway.json` runs `alembic upgrade head` before starting the server.
4. Seed sample data once:
   ```bash
   railway run python scripts/seed_sample_data.py
   ```

## Local Setup

### Option A — Docker (one command)
```bash
docker-compose up
```
The `api` service waits for Postgres to be healthy, runs migrations, then starts. Seed after:
```bash
docker-compose exec api python scripts/seed_sample_data.py
```

### Option B — Manual
1. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   ```
2. Copy `.env.example` to `.env` and adjust `DATABASE_URL` if needed.
3. Start PostgreSQL:
   ```bash
   docker-compose up -d db
   ```
4. Install dependencies:
   ```bash
   python3 -m pip install -e ".[dev]"
   ```
5. Run migrations:
   ```bash
   alembic upgrade head
   ```
6. Seed sample data:
   ```bash
   python3 scripts/seed_sample_data.py
   ```
7. Start the API:
   ```bash
   uvicorn app.main:app --reload
   ```

## Make Targets
- `make install`
- `make migrate`
- `make seed`
- `make run`
- `make test`

## API Overview
- `POST /events` — ingest a payment lifecycle event (idempotent via `event_id`)
- `GET /transactions` — list with merchant/status/date filters, pagination, sorting
- `GET /transactions/{transaction_id}` — detail with merchant info and event timeline
- `GET /reconciliation/summary` — group by merchant, date, or status with per-status counts
- `GET /reconciliation/discrepancies` — discrepant transactions with by_type summary and event timelines
- `GET /health` — DB connectivity and event/transaction counts

See `API.md` for request and response examples.

## Testing
```bash
pytest
```

The main suite uses SQLite for fast local validation. The concurrency test requires a real
Postgres instance and runs when `SETU_TEST_POSTGRES_URL` is set:
```bash
SETU_TEST_POSTGRES_URL=postgresql+asyncpg://... pytest tests/test_concurrency.py
```

## Assumptions and Tradeoffs
- The database stores immutable events plus a query-optimized transactions read model.
- API-facing `status` is derived from `payment_status` and `settlement_status` at query time.
- Exact duplicate event delivery is handled via `event_id` idempotency and does not itself create a discrepancy.
- `processed_not_settled` is a point-in-time discrepancy flag — it clears automatically when a settlement event arrives for that transaction.
- `amount` is set once at `payment_initiated`. Subsequent events for the same transaction do not overwrite it.
- Authentication is intentionally excluded because it is not part of the assignment.
- No caching layer: 10K events and proper indexes make Redis unnecessary at this scale.

## AI Tools Disclosure
This project was designed and built with the assistance of Claude (Anthropic). Claude was used for:
- Architectural planning and trade-off analysis
- Code generation and review
- Test case design

All code has been reviewed, understood, and validated by the submitting engineer.
