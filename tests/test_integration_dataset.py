"""End-to-end ingestion test against the full provided dataset.

Seeds all 10,355 events into an in-memory SQLite database and asserts the exact
discrepancy distribution. This is the strongest correctness signal in the suite —
it exercises the state machine over real, adversarial-ish data (190 duplicate
event_ids, 95 settled-after-failure, 380 processed-not-settled) and holds us to
the ground-truth numbers derived from the sample file.

Opt-in via `RUN_FULL_DATASET_TEST=1` because it seeds 10K+ rows and adds a few
seconds to the default suite. Runs in <15s on SQLite.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import DiscrepancyType, Event, Transaction
from app.schemas import EventIn
from app.services.event_ingestion import ingest_event


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "sample_events.json"


@pytest.mark.skipif(
    not os.getenv("RUN_FULL_DATASET_TEST"),
    reason="Set RUN_FULL_DATASET_TEST=1 to run the full 10K-event integration test.",
)
@pytest.mark.asyncio
async def test_full_dataset_produces_expected_discrepancy_distribution(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'integration.db'}", future=True
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    with DATA_PATH.open() as handle:
        raw_events = json.load(handle)

    try:
        for raw in raw_events:
            payload = EventIn(
                event_id=raw["event_id"],
                event_type=raw["event_type"],
                transaction_id=raw["transaction_id"],
                merchant_id=raw["merchant_id"],
                merchant_name=raw["merchant_name"],
                amount=raw["amount"],
                currency=raw["currency"],
                timestamp=raw["timestamp"],
            )
            async with session_maker() as session:
                await ingest_event(session, payload)

        async with session_maker() as session:
            unique_event_ids = len(set(e["event_id"] for e in raw_events))
            event_count = (
                await session.execute(select(func.count(Event.event_id)))
            ).scalar_one()
            txn_count = (
                await session.execute(select(func.count(Transaction.transaction_id)))
            ).scalar_one()
            disc_rows = (
                await session.execute(
                    select(Transaction.discrepancy_type).where(
                        Transaction.discrepancy_type.is_not(None)
                    )
                )
            ).all()
            disc_counter = Counter(row[0] for row in disc_rows)

        # Ground-truth derived from the sample file: 10,355 raw events with 190
        # duplicate event_ids → 10,165 unique → same number of event rows persisted.
        assert event_count == unique_event_ids == 10_165
        assert txn_count == 3_800

        # 380 processed-not-settled + 95 settled-after-failure + 0 conflicting = 475.
        assert disc_counter[DiscrepancyType.PROCESSED_NOT_SETTLED] == 380
        assert disc_counter[DiscrepancyType.SETTLED_AFTER_FAILURE] == 95
        assert disc_counter[DiscrepancyType.CONFLICTING_STATE_TRANSITION] == 0
        assert sum(disc_counter.values()) == 475
    finally:
        await engine.dispose()
