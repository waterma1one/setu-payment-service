"""Edge-case tests for input validation, duplicate-with-conflict detection,
and error handling paths that the main test_api suite does not cover.

Covers the remaining Task #18 from the original review checklist:
- empty / overlong string fields
- duplicate-with-mutation (duplicate_with_conflict)
- missing required query params (group_by)
- invalid enum values and boundary amounts
- sort functionality
"""
from __future__ import annotations

import uuid

import pytest


def _make_event(
    *,
    event_type: str = "payment_initiated",
    transaction_id: str | None = None,
    merchant_id: str = "merchant_edge",
    merchant_name: str = "EdgeMerchant",
    amount: float = 1000.00,
    currency: str = "INR",
    timestamp: str = "2026-01-10T10:00:00+00:00",
    event_id: str | None = None,
) -> dict:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "transaction_id": transaction_id or str(uuid.uuid4()),
        "merchant_id": merchant_id,
        "merchant_name": merchant_name,
        "amount": amount,
        "currency": currency,
        "timestamp": timestamp,
    }


# ── String validation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_event_id_rejected(client):
    """event_id with min_length=1 should reject empty strings."""
    event = _make_event()
    event["event_id"] = ""
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_transaction_id_rejected(client):
    event = _make_event()
    event["transaction_id"] = ""
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_merchant_id_rejected(client):
    event = _make_event()
    event["merchant_id"] = ""
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_merchant_name_rejected(client):
    event = _make_event()
    event["merchant_name"] = ""
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_overlong_event_id_rejected(client):
    """event_id with max_length=64 should reject 65-char strings."""
    event = _make_event()
    event["event_id"] = "x" * 65
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_overlong_transaction_id_rejected(client):
    event = _make_event()
    event["transaction_id"] = "y" * 65
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_overlong_merchant_id_rejected(client):
    event = _make_event()
    event["merchant_id"] = "z" * 65
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_overlong_merchant_name_rejected(client):
    event = _make_event()
    event["merchant_name"] = "A" * 256
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_max_length_strings_accepted(client):
    """Strings at exactly the max length should be accepted."""
    txn_id = "t" * 64
    event = _make_event(
        event_id="e" * 64,
        transaction_id=txn_id,
        merchant_id="m" * 64,
        merchant_name="N" * 255,
    )
    resp = await client.post("/events", json=event)
    assert resp.status_code == 200
    assert resp.json()["ingestion_status"] == "accepted"


# ── Currency validation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_currency_too_short_rejected(client):
    event = _make_event(currency="IN")
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_currency_too_long_rejected(client):
    event = _make_event(currency="INRR")
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_currency_lowercased_normalised(client):
    """Currency should be uppercased automatically."""
    txn_id = str(uuid.uuid4())
    event = _make_event(transaction_id=txn_id, currency="inr")
    resp = await client.post("/events", json=event)
    assert resp.status_code == 200
    detail = await client.get(f"/transactions/{txn_id}")
    assert detail.json()["transaction"]["currency"] == "INR"


# ── Amount boundary ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zero_amount_rejected(client):
    """amount must be > 0, not >= 0."""
    event = _make_event(amount=0)
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


# ── Invalid event_type ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_event_type_rejected(client):
    event = _make_event(event_type="refunded")
    resp = await client.post("/events", json=event)
    assert resp.status_code == 422


# ── Duplicate with conflict ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_with_different_amount_returns_conflict(client):
    """Re-submitting the same event_id with a different amount should return
    duplicate_with_conflict instead of plain duplicate."""
    txn_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    original = _make_event(
        event_id=event_id, transaction_id=txn_id, amount=1000.00
    )
    resp1 = await client.post("/events", json=original)
    assert resp1.status_code == 200
    assert resp1.json()["ingestion_status"] == "accepted"

    mutated = _make_event(
        event_id=event_id, transaction_id=txn_id, amount=9999.99
    )
    resp2 = await client.post("/events", json=mutated)
    assert resp2.status_code == 200
    assert resp2.json()["ingestion_status"] == "duplicate_with_conflict"


@pytest.mark.asyncio
async def test_duplicate_with_different_event_type_returns_conflict(client):
    txn_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    original = _make_event(
        event_id=event_id, transaction_id=txn_id, event_type="payment_initiated"
    )
    await client.post("/events", json=original)

    mutated = _make_event(
        event_id=event_id, transaction_id=txn_id, event_type="payment_processed"
    )
    resp = await client.post("/events", json=mutated)
    assert resp.status_code == 200
    assert resp.json()["ingestion_status"] == "duplicate_with_conflict"


@pytest.mark.asyncio
async def test_exact_duplicate_returns_plain_duplicate(client):
    """Exact same payload should return plain 'duplicate', not 'duplicate_with_conflict'."""
    txn_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    event = _make_event(event_id=event_id, transaction_id=txn_id)

    await client.post("/events", json=event)
    resp = await client.post("/events", json=event)
    assert resp.status_code == 200
    assert resp.json()["ingestion_status"] == "duplicate"


# ── Missing required query params ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconciliation_summary_missing_group_by_rejected(client):
    """group_by is required for /reconciliation/summary."""
    resp = await client.get("/reconciliation/summary")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reconciliation_summary_invalid_group_by_rejected(client):
    """Invalid group_by value should be rejected by the regex pattern."""
    resp = await client.get("/reconciliation/summary?group_by=foobar")
    assert resp.status_code == 422


# ── Invalid status filter ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_transactions_invalid_status_rejected(client):
    resp = await client.get("/transactions?status=unknown_status")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_discrepancies_invalid_type_rejected(client):
    resp = await client.get("/reconciliation/discrepancies?type=invalid_type")
    assert resp.status_code == 422


# ── Sort functionality ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sort_by_amount_ascending(client):
    """Sort by amount ascending should return lowest amounts first."""
    merchant_id = "merchant_sort_test"
    amounts = [500.00, 1500.00, 100.00]
    for amount in amounts:
        txn_id = str(uuid.uuid4())
        await client.post("/events", json=_make_event(
            transaction_id=txn_id,
            merchant_id=merchant_id,
            amount=amount,
        ))

    resp = await client.get(
        f"/transactions?merchant_id={merchant_id}&sort_by=amount&sort_order=asc"
    )
    assert resp.status_code == 200
    result_amounts = [float(t["amount"]) for t in resp.json()["transactions"]]
    assert result_amounts == sorted(result_amounts)


@pytest.mark.asyncio
async def test_sort_by_amount_descending(client):
    merchant_id = "merchant_sort_desc"
    amounts = [500.00, 1500.00, 100.00]
    for amount in amounts:
        txn_id = str(uuid.uuid4())
        await client.post("/events", json=_make_event(
            transaction_id=txn_id,
            merchant_id=merchant_id,
            amount=amount,
        ))

    resp = await client.get(
        f"/transactions?merchant_id={merchant_id}&sort_by=amount&sort_order=desc"
    )
    assert resp.status_code == 200
    result_amounts = [float(t["amount"]) for t in resp.json()["transactions"]]
    assert result_amounts == sorted(result_amounts, reverse=True)


@pytest.mark.asyncio
async def test_invalid_sort_by_rejected(client):
    resp = await client.get("/transactions?sort_by=invalid_field")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_sort_order_rejected(client):
    resp = await client.get("/transactions?sort_order=sideways")
    assert resp.status_code == 422


# ── Immutable amount after initiation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_amount_immutable_after_initiation(client):
    """Amount is set during payment_initiated and should not change on
    subsequent events, even if they carry a different amount value."""
    txn_id = str(uuid.uuid4())

    await client.post("/events", json=_make_event(
        transaction_id=txn_id, event_type="payment_initiated",
        amount=1000.00, timestamp="2026-01-10T10:00:00+00:00",
    ))

    # Process event carries a different amount — should be ignored for txn.amount
    await client.post("/events", json=_make_event(
        transaction_id=txn_id, event_type="payment_processed",
        amount=9999.99, timestamp="2026-01-10T10:05:00+00:00",
    ))

    resp = await client.get(f"/transactions/{txn_id}")
    assert resp.status_code == 200
    assert float(resp.json()["transaction"]["amount"]) == 1000.00


# ── Pagination edge cases ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_page_beyond_total_returns_empty(client):
    """Requesting page=999 should return an empty list, not an error."""
    resp = await client.get("/transactions?page=999")
    assert resp.status_code == 200
    assert resp.json()["transactions"] == []


@pytest.mark.asyncio
async def test_per_page_exceeding_max_rejected(client):
    """per_page > 100 should be rejected."""
    resp = await client.get("/transactions?per_page=101")
    assert resp.status_code == 422
