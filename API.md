# API Contract

## POST /events
Ingest a payment lifecycle event. Idempotent: re-sending the same `event_id` returns `"duplicate"` with no state mutation. If the re-submitted payload differs from the stored event in any field, the response is `"duplicate_with_conflict"` and a warning is logged.

**Validation rules:**
- `event_id`, `transaction_id`, `merchant_id`: 1–64 characters
- `merchant_name`: 1–255 characters
- `amount` must be greater than zero
- `currency` must be exactly 3 characters (normalised to uppercase)
- `event_type` must be one of: `payment_initiated`, `payment_processed`, `payment_failed`, `settled`
- `timestamp` must not be in the future

Request:
```json
{
  "event_id": "b768e3a7-9eb3-4603-b21c-a54cc95661bc",
  "event_type": "payment_initiated",
  "transaction_id": "2f86e94c-239c-4302-9874-75f28e3474ee",
  "merchant_id": "merchant_2",
  "merchant_name": "FreshBasket",
  "amount": 15248.29,
  "currency": "INR",
  "timestamp": "2026-01-08T12:11:58.085567+00:00"
}
```

Success response (`ingestion_status: "accepted"`):
```json
{
  "ingestion_status": "accepted",
  "transaction_id": "2f86e94c-239c-4302-9874-75f28e3474ee",
  "payment_status": "initiated",
  "settlement_status": "pending",
  "status": "initiated",
  "discrepancy_type": null
}
```

Duplicate response (same `event_id`, no state change):
```json
{
  "ingestion_status": "duplicate",
  "transaction_id": "2f86e94c-239c-4302-9874-75f28e3474ee",
  "payment_status": "initiated",
  "settlement_status": "pending",
  "status": "initiated",
  "discrepancy_type": null
}
```

Duplicate-with-conflict (same `event_id`, but resubmitted payload differs — e.g. mutated `amount`):
```json
{
  "ingestion_status": "duplicate_with_conflict",
  "transaction_id": "2f86e94c-239c-4302-9874-75f28e3474ee",
  "payment_status": "initiated",
  "settlement_status": "pending",
  "status": "initiated",
  "discrepancy_type": null
}
```

## GET /transactions
Query params:
- `merchant_id` — filter by merchant
- `status` — one of: `initiated`, `processed_pending_settlement`, `settled`, `failed`
- `start_date` / `end_date` — ISO 8601 datetime range on `created_at`
- `page` (default 1), `per_page` (default 20, max 100)
- `sort_by` — `created_at` | `amount` | `status` (default `created_at`)
- `sort_order` — `asc` | `desc` (default `desc`)

Response:
```json
{
  "transactions": [
    {
      "transaction_id": "2f86e94c-239c-4302-9874-75f28e3474ee",
      "amount": "15248.29",
      "currency": "INR",
      "payment_status": "failed",
      "settlement_status": "pending",
      "status": "failed",
      "discrepancy_type": null,
      "created_at": "2026-01-08T12:11:58.085567+00:00",
      "updated_at": "2026-01-08T12:38:58.085567+00:00",
      "last_event_timestamp": "2026-01-08T12:38:58.085567+00:00"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 3800,
    "total_pages": 190
  }
}
```

## GET /transactions/{transaction_id}
Returns transaction details, merchant details, and ordered event timeline.

```json
{
  "transaction": {
    "transaction_id": "2f86e94c-239c-4302-9874-75f28e3474ee",
    "amount": "15248.29",
    "currency": "INR",
    "payment_status": "failed",
    "settlement_status": "pending",
    "status": "failed",
    "discrepancy_type": null,
    "created_at": "2026-01-08T12:11:58.085567+00:00",
    "updated_at": "2026-01-08T12:38:58.085567+00:00",
    "last_event_timestamp": "2026-01-08T12:38:58.085567+00:00"
  },
  "merchant": {
    "merchant_id": "merchant_2",
    "merchant_name": "FreshBasket"
  },
  "events": [
    { "event_id": "b768e3a7-...", "event_type": "payment_initiated", "timestamp": "2026-01-08T12:11:58+00:00", "amount": "15248.29", "currency": "INR" },
    { "event_id": "c891f2a8-...", "event_type": "payment_failed",    "timestamp": "2026-01-08T12:38:58+00:00", "amount": "15248.29", "currency": "INR" }
  ]
}
```

Returns `404` if `transaction_id` does not exist.

## GET /reconciliation/summary
Returns per-group transaction counts broken down by derived status and discrepancy presence.

Query params:
- `group_by` — `merchant` | `date` | `status` (**required**)
- `merchant_id` — optional filter
- `start_date` / `end_date` — optional date range

Response (`group_by=merchant`):
```json
{
  "group_by": "merchant",
  "summaries": [
    {
      "group": "merchant_1",
      "transaction_count": 800,
      "total_amount": "9823451.00",
      "avg_amount": "12279.31",
      "initiated_count": 120,
      "processed_count": 180,
      "settled_count": 450,
      "failed_count": 50,
      "discrepancy_count": 32
    }
  ]
}
```

`processed_count` represents transactions in `processed_pending_settlement` state.

## GET /reconciliation/discrepancies
Returns transactions where payment and settlement state are inconsistent.

Query params:
- `type` — optional filter: `processed_not_settled` | `settled_after_failure` | `conflicting_state_transition`
- `merchant_id` — optional filter
- `page`, `per_page`

Discrepancy types:
| Type | Description |
|------|-------------|
| `processed_not_settled` | Payment processed but settlement has not arrived |
| `settled_after_failure` | Settlement recorded for a payment that was marked failed |
| `conflicting_state_transition` | A unique event implied a contradictory lifecycle change |

Response:
```json
{
  "discrepancies": [
    {
      "transaction_id": "482ec6cc-8e86-4f4f-adb2-2f74e2bbf0da",
      "merchant_id": "merchant_3",
      "merchant_name": "QuickPay",
      "amount": "8500.00",
      "currency": "INR",
      "payment_status": "failed",
      "settlement_status": "settled",
      "status": "failed",
      "discrepancy_type": "settled_after_failure",
      "description": "Settlement recorded for a failed payment.",
      "event_timeline": [
        { "event_id": "aaa...", "event_type": "payment_initiated", "timestamp": "2026-01-10T08:00:00+00:00", "amount": "8500.00", "currency": "INR" },
        { "event_id": "bbb...", "event_type": "payment_failed",    "timestamp": "2026-01-10T08:05:00+00:00", "amount": "8500.00", "currency": "INR" },
        { "event_id": "ccc...", "event_type": "settled",           "timestamp": "2026-01-10T09:00:00+00:00", "amount": "8500.00", "currency": "INR" }
      ]
    }
  ],
  "summary": {
    "total": 475,
    "by_type": {
      "processed_not_settled": 380,
      "settled_after_failure": 95,
      "conflicting_state_transition": 0
    }
  },
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 475,
    "total_pages": 24
  }
}
```

Note: `summary.by_type` always reflects the global distribution for the current merchant filter,
regardless of the `type` filter param. This lets ops see the full breakdown even while drilling
into a specific type.

## GET /health

```json
{
  "status": "healthy",
  "database": "connected",
  "event_count": 10355,
  "transaction_count": 3800
}
```

Returns `503` if the database is unreachable.

## Error Responses

All error responses share FastAPI's default `{"detail": ...}` shape.

Validation error (`422 Unprocessable Entity`):
```json
{
  "detail": [
    {
      "type": "greater_than",
      "loc": ["body", "amount"],
      "msg": "Input should be greater than 0",
      "input": -100.0,
      "ctx": {"gt": 0}
    }
  ]
}
```

Not found (`404 Not Found`):
```json
{
  "detail": "Transaction not found"
}
```

Database unavailable (`503 Service Unavailable`):
```json
{
  "detail": "Database unavailable"
}
```

The 503 body deliberately does not echo driver-level exception text (which may contain the DSN). Details are logged server-side instead.

