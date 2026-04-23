"""Parity test: the Python-side `derive_status` and the SQL-side `STATUS_CASE` must
agree on every possible (payment_status, settlement_status) pair. These two
implementations are kept separate for performance (SQL-side filtering) but drift
between them would cause silent wrong-bucket bugs in list/summary endpoints.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import PaymentStatus, SettlementStatus, Transaction
from app.schemas import derive_status
from app.services.reconciliation import STATUS_CASE


ALL_COMBINATIONS = [
    (p, s)
    for p in PaymentStatus
    for s in SettlementStatus
]


@pytest.mark.asyncio
async def test_derive_status_matches_status_case_for_every_combination(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'parity.db'}", future=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_maker() as session:
            from app.models import Merchant
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            session.add(Merchant(merchant_id="m1", merchant_name="M1", created_at=now, updated_at=now))
            for i, (payment, settlement) in enumerate(ALL_COMBINATIONS):
                session.add(
                    Transaction(
                        transaction_id=f"txn_{i}",
                        merchant_id="m1",
                        amount=100,
                        currency="INR",
                        payment_status=payment,
                        settlement_status=settlement,
                        created_at=now,
                        updated_at=now,
                        last_event_timestamp=now,
                    )
                )
            await session.commit()

        async with session_maker() as session:
            rows = (
                await session.execute(
                    select(
                        Transaction.payment_status,
                        Transaction.settlement_status,
                        STATUS_CASE.label("sql_status"),
                    )
                )
            ).all()

        for payment, settlement, sql_status in rows:
            py_status = derive_status(payment, settlement)
            assert sql_status == py_status, (
                f"Parity mismatch for ({payment.value}, {settlement.value}): "
                f"SQL={sql_status!r} Python={py_status!r}"
            )

        assert len(rows) == len(ALL_COMBINATIONS) == 6
    finally:
        await engine.dispose()
