from __future__ import annotations

import uuid

import pytest


def _make_event(
    *,
    event_type: str,
    transaction_id: str,
    merchant_id: str = "merchant_1",
    merchant_name: str = "TestMerchant",
    amount: float = 1000.00,
    currency: str = "INR",
    timestamp: str = "2026-01-10T10:00:00+00:00",
    event_id: str | None = None,
) -> dict:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "transaction_id": transaction_id,
        "merchant_id": merchant_id,
        "merchant_name": merchant_name,
        "amount": amount,
        "currency": currency,
        "timestamp": timestamp,
    }


@pytest.mark.asyncio
async def test_payment_initiated_returns_initiated_status(client):
    txn_id = str(uuid.uuid4())
    resp = await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id
    ))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ingestion_status"] == "accepted"
    assert body["status"] == "initiated"
    # Pydantic serialises PaymentStatus (a str-enum) using its .value (lowercase)
    assert body["payment_status"] == "initiated"
    assert body["settlement_status"] == "pending"
    assert body["discrepancy_type"] is None


@pytest.mark.asyncio
async def test_duplicate_event_is_idempotent(client):
    txn_id = str(uuid.uuid4())
    event = _make_event(event_type="payment_initiated", transaction_id=txn_id)

    first = await client.post("/events", json=event)
    second = await client.post("/events", json=event)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["ingestion_status"] == "duplicate"
    assert second.json()["status"] == first.json()["status"]


@pytest.mark.asyncio
async def test_happy_path_full_lifecycle(client):
    txn_id = str(uuid.uuid4())

    await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id,
        timestamp="2026-01-10T10:00:00+00:00",
    ))
    r2 = await client.post("/events", json=_make_event(
        event_type="payment_processed", transaction_id=txn_id,
        timestamp="2026-01-10T10:05:00+00:00",
    ))
    assert r2.json()["status"] == "processed_pending_settlement"

    r3 = await client.post("/events", json=_make_event(
        event_type="settled", transaction_id=txn_id,
        timestamp="2026-01-10T10:10:00+00:00",
    ))
    assert r3.json()["status"] == "settled"
    assert r3.json()["discrepancy_type"] is None


@pytest.mark.asyncio
async def test_processed_not_settled_is_discrepant(client):
    txn_id = str(uuid.uuid4())

    await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id,
        timestamp="2026-01-10T10:00:00+00:00",
    ))
    await client.post("/events", json=_make_event(
        event_type="payment_processed", transaction_id=txn_id,
        timestamp="2026-01-10T10:05:00+00:00",
    ))

    resp = await client.get(f"/transactions/{txn_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction"]["discrepancy_type"] == "processed_not_settled"
    assert body["transaction"]["status"] == "processed_pending_settlement"


@pytest.mark.asyncio
async def test_processed_not_settled_clears_after_settlement(client):
    txn_id = str(uuid.uuid4())

    for event_type, ts in [
        ("payment_initiated", "2026-01-10T10:00:00+00:00"),
        ("payment_processed", "2026-01-10T10:05:00+00:00"),
        ("settled", "2026-01-10T10:10:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=txn_id, timestamp=ts
        ))

    resp = await client.get(f"/transactions/{txn_id}")
    assert resp.json()["transaction"]["discrepancy_type"] is None
    assert resp.json()["transaction"]["status"] == "settled"


@pytest.mark.asyncio
async def test_settled_after_failure_is_discrepant(client):
    txn_id = str(uuid.uuid4())

    for event_type, ts in [
        ("payment_initiated", "2026-01-10T10:00:00+00:00"),
        ("payment_failed", "2026-01-10T10:05:00+00:00"),
        ("settled", "2026-01-10T10:10:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=txn_id, timestamp=ts
        ))

    resp = await client.get(f"/transactions/{txn_id}")
    assert resp.status_code == 200
    assert resp.json()["transaction"]["discrepancy_type"] == "settled_after_failure"
    assert resp.json()["transaction"]["status"] == "failed"


@pytest.mark.asyncio
async def test_payment_failed_blocks_to_correct_status(client):
    txn_id = str(uuid.uuid4())

    await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id,
        timestamp="2026-01-10T10:00:00+00:00",
    ))
    r = await client.post("/events", json=_make_event(
        event_type="payment_failed", transaction_id=txn_id,
        timestamp="2026-01-10T10:05:00+00:00",
    ))
    assert r.json()["status"] == "failed"
    assert r.json()["discrepancy_type"] is None


@pytest.mark.asyncio
async def test_conflicting_state_transition_on_reinitiation(client):
    txn_id = str(uuid.uuid4())

    await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id,
        timestamp="2026-01-10T10:00:00+00:00",
    ))
    await client.post("/events", json=_make_event(
        event_type="payment_processed", transaction_id=txn_id,
        timestamp="2026-01-10T10:05:00+00:00",
    ))
    # A new unique event with payment_initiated again (not a duplicate — different event_id)
    r = await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id,
        timestamp="2026-01-10T10:06:00+00:00",
    ))
    assert r.json()["discrepancy_type"] == "conflicting_state_transition"


@pytest.mark.asyncio
async def test_future_timestamp_rejected(client):
    txn_id = str(uuid.uuid4())
    resp = await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id,
        timestamp="2099-12-31T00:00:00+00:00",
    ))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_negative_amount_rejected(client):
    txn_id = str(uuid.uuid4())
    resp = await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id,
        amount=-100.0,
    ))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_transactions_pagination_and_filters(client):
    merchant_id = "merchant_list_test"
    for i in range(5):
        txn_id = str(uuid.uuid4())
        await client.post("/events", json=_make_event(
            event_type="payment_initiated",
            transaction_id=txn_id,
            merchant_id=merchant_id,
            merchant_name="ListTestMerchant",
        ))

    resp = await client.get(f"/transactions?merchant_id={merchant_id}&per_page=3&page=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"]["total"] == 5
    assert body["pagination"]["total_pages"] == 2
    assert len(body["transactions"]) == 3


@pytest.mark.asyncio
async def test_list_transactions_status_filter(client):
    txn_id = str(uuid.uuid4())
    for event_type, ts in [
        ("payment_initiated", "2026-01-10T10:00:00+00:00"),
        ("payment_failed", "2026-01-10T10:05:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=txn_id, timestamp=ts
        ))

    resp = await client.get("/transactions?status=failed")
    assert resp.status_code == 200
    txn_ids = [t["transaction_id"] for t in resp.json()["transactions"]]
    assert txn_id in txn_ids


@pytest.mark.asyncio
async def test_transaction_detail_includes_merchant_and_events(client):
    txn_id = str(uuid.uuid4())
    await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id,
        merchant_name="DetailMerchant",
    ))

    resp = await client.get(f"/transactions/{txn_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["merchant"]["merchant_name"] == "DetailMerchant"
    assert len(body["events"]) == 1
    assert body["events"][0]["event_type"] == "payment_initiated"


@pytest.mark.asyncio
async def test_transaction_detail_returns_404_for_unknown_id(client):
    resp = await client.get(f"/transactions/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reconciliation_summary_merchant_group(client):
    for i in range(3):
        txn_id = str(uuid.uuid4())
        await client.post("/events", json=_make_event(
            event_type="payment_initiated",
            transaction_id=txn_id,
            merchant_id="merchant_summary_a",
            merchant_name="SummaryMerchantA",
        ))

    resp = await client.get("/reconciliation/summary?group_by=merchant")
    assert resp.status_code == 200
    body = resp.json()
    groups = {s["group"]: s for s in body["summaries"]}
    assert "merchant_summary_a" in groups
    item = groups["merchant_summary_a"]
    assert item["transaction_count"] == 3
    assert item["initiated_count"] == 3
    assert item["settled_count"] == 0
    assert item["discrepancy_count"] == 0
    assert "avg_amount" in item


@pytest.mark.asyncio
async def test_reconciliation_summary_status_group(client):
    txn_id = str(uuid.uuid4())
    for event_type, ts in [
        ("payment_initiated", "2026-01-10T10:00:00+00:00"),
        ("payment_processed", "2026-01-10T10:05:00+00:00"),
        ("settled", "2026-01-10T10:10:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=txn_id, timestamp=ts
        ))

    resp = await client.get("/reconciliation/summary?group_by=status")
    assert resp.status_code == 200
    groups = {s["group"] for s in resp.json()["summaries"]}
    assert "settled" in groups


@pytest.mark.asyncio
async def test_discrepancy_report_includes_by_type_summary(client):
    txn_id = str(uuid.uuid4())
    for event_type, ts in [
        ("payment_initiated", "2026-01-10T10:00:00+00:00"),
        ("payment_failed", "2026-01-10T10:05:00+00:00"),
        ("settled", "2026-01-10T10:10:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=txn_id, timestamp=ts
        ))

    resp = await client.get("/reconciliation/discrepancies")
    assert resp.status_code == 200
    body = resp.json()
    assert "summary" in body
    assert "total" in body["summary"]
    assert "by_type" in body["summary"]
    assert body["summary"]["total"] >= 1
    assert "settled_after_failure" in body["summary"]["by_type"]


@pytest.mark.asyncio
async def test_discrepancy_report_includes_event_timeline(client):
    txn_id = str(uuid.uuid4())
    for event_type, ts in [
        ("payment_initiated", "2026-01-10T10:00:00+00:00"),
        ("payment_failed", "2026-01-10T10:05:00+00:00"),
        ("settled", "2026-01-10T10:10:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=txn_id, timestamp=ts
        ))

    resp = await client.get("/reconciliation/discrepancies")
    body = resp.json()
    target = next((d for d in body["discrepancies"] if d["transaction_id"] == txn_id), None)
    assert target is not None
    assert len(target["event_timeline"]) == 3
    types = [e["event_type"] for e in target["event_timeline"]]
    assert types == ["payment_initiated", "payment_failed", "settled"]


@pytest.mark.asyncio
async def test_root_endpoint(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert "service" in body
    assert "docs" in body


@pytest.mark.asyncio
async def test_naive_timestamp_is_accepted(client):
    """Timestamps without timezone info should be accepted (treated as UTC)."""
    txn_id = str(uuid.uuid4())
    resp = await client.post("/events", json=_make_event(
        event_type="payment_initiated",
        transaction_id=txn_id,
        timestamp="2026-01-10T10:00:00",  # no timezone info
    ))
    assert resp.status_code == 200
    assert resp.json()["ingestion_status"] == "accepted"


@pytest.mark.asyncio
async def test_health_returns_connected(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["database"] == "connected"
    assert "event_count" in body
    assert "transaction_count" in body


# ── Conflict branches ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_conflict_settled_on_initiated_transaction(client):
    """SETTLED arriving before any payment event → conflicting_state_transition."""
    txn_id = str(uuid.uuid4())
    await client.post("/events", json=_make_event(
        event_type="payment_initiated", transaction_id=txn_id,
        timestamp="2026-01-10T10:00:00+00:00",
    ))
    r = await client.post("/events", json=_make_event(
        event_type="settled", transaction_id=txn_id,
        timestamp="2026-01-10T10:05:00+00:00",
    ))
    assert r.status_code == 200
    assert r.json()["discrepancy_type"] == "conflicting_state_transition"


@pytest.mark.asyncio
async def test_conflict_payment_failed_after_processed(client):
    """PAYMENT_FAILED arriving after PAYMENT_PROCESSED → conflicting_state_transition."""
    txn_id = str(uuid.uuid4())
    for event_type, ts in [
        ("payment_initiated", "2026-01-10T10:00:00+00:00"),
        ("payment_processed", "2026-01-10T10:05:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=txn_id, timestamp=ts
        ))
    r = await client.post("/events", json=_make_event(
        event_type="payment_failed", transaction_id=txn_id,
        timestamp="2026-01-10T10:10:00+00:00",
    ))
    assert r.status_code == 200
    assert r.json()["discrepancy_type"] == "conflicting_state_transition"


@pytest.mark.asyncio
async def test_conflict_payment_processed_after_failed(client):
    """PAYMENT_PROCESSED arriving after PAYMENT_FAILED → conflicting_state_transition."""
    txn_id = str(uuid.uuid4())
    for event_type, ts in [
        ("payment_initiated", "2026-01-10T10:00:00+00:00"),
        ("payment_failed", "2026-01-10T10:05:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=txn_id, timestamp=ts
        ))
    r = await client.post("/events", json=_make_event(
        event_type="payment_processed", transaction_id=txn_id,
        timestamp="2026-01-10T10:10:00+00:00",
    ))
    assert r.status_code == 200
    assert r.json()["discrepancy_type"] == "conflicting_state_transition"


# ── Date range filters ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_transactions_date_range_filter(client):
    """Transactions outside the date range should be excluded."""
    merchant_id = "merchant_date_range"

    # inside range
    txn_in = str(uuid.uuid4())
    await client.post("/events", json=_make_event(
        event_type="payment_initiated",
        transaction_id=txn_in,
        merchant_id=merchant_id,
        merchant_name="DateRangeMerchant",
        timestamp="2026-03-15T12:00:00+00:00",
    ))

    # outside range (too early)
    txn_out = str(uuid.uuid4())
    await client.post("/events", json=_make_event(
        event_type="payment_initiated",
        transaction_id=txn_out,
        merchant_id=merchant_id,
        merchant_name="DateRangeMerchant",
        timestamp="2026-01-01T00:00:00+00:00",
    ))

    resp = await client.get(
        f"/transactions?merchant_id={merchant_id}"
        "&start_date=2026-03-01T00:00:00Z&end_date=2026-03-31T23:59:59Z"
    )
    assert resp.status_code == 200
    ids = [t["transaction_id"] for t in resp.json()["transactions"]]
    assert txn_in in ids
    assert txn_out not in ids


@pytest.mark.asyncio
async def test_reconciliation_summary_date_range_filter(client):
    """Summary with date range excludes out-of-range transactions."""
    merchant_id = "merchant_summary_date"

    txn_in = str(uuid.uuid4())
    await client.post("/events", json=_make_event(
        event_type="payment_initiated",
        transaction_id=txn_in,
        merchant_id=merchant_id,
        merchant_name="SummaryDateMerchant",
        timestamp="2026-03-15T00:00:00+00:00",
    ))

    txn_out = str(uuid.uuid4())
    await client.post("/events", json=_make_event(
        event_type="payment_initiated",
        transaction_id=txn_out,
        merchant_id=merchant_id,
        merchant_name="SummaryDateMerchant",
        timestamp="2026-01-01T00:00:00+00:00",
    ))

    resp = await client.get(
        "/reconciliation/summary?group_by=merchant"
        f"&merchant_id={merchant_id}"
        "&start_date=2026-03-01T00:00:00Z&end_date=2026-03-31T23:59:59Z"
    )
    assert resp.status_code == 200
    summaries = resp.json()["summaries"]
    assert len(summaries) == 1
    assert summaries[0]["transaction_count"] == 1


# ── Reconciliation summary group_by=date ────────────────────────────────────

@pytest.mark.asyncio
async def test_reconciliation_summary_date_group(client):
    txn_id = str(uuid.uuid4())
    for event_type, ts in [
        ("payment_initiated", "2026-02-10T10:00:00+00:00"),
        ("payment_processed", "2026-02-10T10:05:00+00:00"),
        ("settled", "2026-02-10T10:10:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=txn_id, timestamp=ts
        ))

    resp = await client.get("/reconciliation/summary?group_by=date")
    assert resp.status_code == 200
    groups = {s["group"] for s in resp.json()["summaries"]}
    assert any("2026-02-10" in g for g in groups)


# ── Discrepancy type filter and pagination ───────────────────────────────────

@pytest.mark.asyncio
async def test_discrepancy_type_filter(client):
    """?type filter returns only the requested discrepancy type."""
    saf_txn = str(uuid.uuid4())
    for event_type, ts in [
        ("payment_initiated", "2026-01-10T10:00:00+00:00"),
        ("payment_failed",    "2026-01-10T10:05:00+00:00"),
        ("settled",           "2026-01-10T10:10:00+00:00"),
    ]:
        await client.post("/events", json=_make_event(
            event_type=event_type, transaction_id=saf_txn, timestamp=ts
        ))

    resp = await client.get("/reconciliation/discrepancies?type=settled_after_failure")
    assert resp.status_code == 200
    body = resp.json()
    for row in body["discrepancies"]:
        assert row["discrepancy_type"] == "settled_after_failure"
    assert saf_txn in [d["transaction_id"] for d in body["discrepancies"]]


@pytest.mark.asyncio
async def test_discrepancy_pagination(client):
    """Pagination metadata is correct for the discrepancy endpoint."""
    merchant_id = "merchant_disc_page"
    for _ in range(3):
        txn_id = str(uuid.uuid4())
        for event_type, ts in [
            ("payment_initiated", "2026-01-10T10:00:00+00:00"),
            ("payment_failed",    "2026-01-10T10:05:00+00:00"),
            ("settled",           "2026-01-10T10:10:00+00:00"),
        ]:
            await client.post("/events", json=_make_event(
                event_type=event_type,
                transaction_id=txn_id,
                merchant_id=merchant_id,
                merchant_name="DiscPageMerchant",
                timestamp=ts,
            ))

    resp = await client.get(
        f"/reconciliation/discrepancies?merchant_id={merchant_id}&per_page=2&page=1"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"]["total"] == 3
    assert body["pagination"]["total_pages"] == 2
    assert len(body["discrepancies"]) == 2
