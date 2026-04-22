from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Transaction
from app.schemas import EventIn
from app.services.event_ingestion import ingest_event


pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(
    not os.getenv("SETU_TEST_POSTGRES_URL"),
    reason="Requires SETU_TEST_POSTGRES_URL for real Postgres concurrency verification.",
)
async def test_concurrent_first_write_creates_single_transaction_row():
    engine = create_async_engine(os.environ["SETU_TEST_POSTGRES_URL"], future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    payload_one = EventIn(
        event_id="20000000-0000-0000-0000-000000000001",
        event_type="payment_initiated",
        transaction_id="30000000-0000-0000-0000-000000000001",
        merchant_id="merchant_concurrent",
        merchant_name="Concurrent Merchant",
        amount="10.00",
        currency="INR",
        timestamp="2026-04-22T00:00:00+00:00",
    )
    payload_two = EventIn(
        event_id="20000000-0000-0000-0000-000000000002",
        event_type="payment_processed",
        transaction_id="30000000-0000-0000-0000-000000000001",
        merchant_id="merchant_concurrent",
        merchant_name="Concurrent Merchant",
        amount="10.00",
        currency="INR",
        timestamp="2026-04-22T00:01:00+00:00",
    )

    async def run_ingest(payload):
        async with session_maker() as session:
            return await ingest_event(session, payload)

    await asyncio.gather(run_ingest(payload_one), run_ingest(payload_two))

    async with session_maker() as session:
        count = (
            await session.execute(select(func.count(Transaction.transaction_id)))
        ).scalar_one()
    assert count == 1
    await engine.dispose()
