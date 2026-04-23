from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import (
    DiscrepancyType,
    Event,
    EventType,
    Merchant,
    PaymentStatus,
    SettlementStatus,
    Transaction,
)
from app.schemas import EventIn, EventIngestionResponse, derive_status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def describe_discrepancy(discrepancy_type: Optional[DiscrepancyType]) -> Optional[str]:
    mapping = {
        DiscrepancyType.PROCESSED_NOT_SETTLED: "Payment processed but not settled.",
        DiscrepancyType.SETTLED_AFTER_FAILURE: "Settlement recorded for a failed payment.",
        DiscrepancyType.CONFLICTING_STATE_TRANSITION: "A unique event implied a conflicting lifecycle transition.",
    }
    return mapping.get(discrepancy_type)


def recompute_discrepancy(
    transaction: Transaction,
    conflict_detected: bool = False,
) -> Optional[DiscrepancyType]:
    if conflict_detected or transaction.discrepancy_type == DiscrepancyType.CONFLICTING_STATE_TRANSITION:
        return DiscrepancyType.CONFLICTING_STATE_TRANSITION
    if (
        transaction.payment_status == PaymentStatus.FAILED
        and transaction.settlement_status == SettlementStatus.SETTLED
    ):
        return DiscrepancyType.SETTLED_AFTER_FAILURE
    if (
        transaction.payment_status == PaymentStatus.PROCESSED
        and transaction.settlement_status == SettlementStatus.PENDING
    ):
        return DiscrepancyType.PROCESSED_NOT_SETTLED
    return None


async def get_transaction_snapshot(
    session: AsyncSession, transaction_id: str
) -> EventIngestionResponse:
    transaction = await session.get(Transaction, transaction_id)
    if transaction is None:  # pragma: no cover
        raise ValueError(f"Transaction {transaction_id} was not found after ingestion.")
    return EventIngestionResponse(
        ingestion_status="accepted",
        transaction_id=transaction.transaction_id,
        payment_status=transaction.payment_status,
        settlement_status=transaction.settlement_status,
        status=derive_status(transaction.payment_status, transaction.settlement_status),
        discrepancy_type=transaction.discrepancy_type,
    )


async def ingest_event(session: AsyncSession, payload: EventIn) -> EventIngestionResponse:
    now = _ensure_utc(_now())
    payload_timestamp = _ensure_utc(payload.timestamp)
    try:
        async with session.begin():
            event = Event(
                event_id=payload.event_id,
                transaction_id=payload.transaction_id,
                merchant_id=payload.merchant_id,
                event_type=payload.event_type,
                amount=payload.amount,
                currency=payload.currency,
                event_timestamp=payload_timestamp,
                received_at=now,
            )
            session.add(event)

            merchant = await session.get(Merchant, payload.merchant_id)
            if merchant is None:
                merchant = Merchant(
                    merchant_id=payload.merchant_id,
                    merchant_name=payload.merchant_name,
                    created_at=now,
                    updated_at=now,
                )
                session.add(merchant)
            else:
                merchant.merchant_name = payload.merchant_name
                merchant.updated_at = now

            conn = await session.connection()
            if conn.dialect.name == "postgresql":  # pragma: no cover
                shell_insert = pg_insert(Transaction).values(
                    transaction_id=payload.transaction_id,
                    merchant_id=payload.merchant_id,
                    amount=payload.amount,
                    currency=payload.currency,
                    payment_status=PaymentStatus.INITIATED,
                    settlement_status=SettlementStatus.PENDING,
                    discrepancy_type=None,
                    created_at=payload_timestamp,
                    updated_at=now,
                    last_event_timestamp=payload_timestamp,
                )
                shell_insert = shell_insert.on_conflict_do_nothing(
                    index_elements=["transaction_id"]
                )
                await session.execute(shell_insert)
            else:
                transaction = await session.get(Transaction, payload.transaction_id)
                if transaction is None:
                    session.add(
                        Transaction(
                            transaction_id=payload.transaction_id,
                            merchant_id=payload.merchant_id,
                            amount=payload.amount,
                            currency=payload.currency,
                            payment_status=PaymentStatus.INITIATED,
                            settlement_status=SettlementStatus.PENDING,
                            discrepancy_type=None,
                            created_at=payload_timestamp,
                            updated_at=now,
                            last_event_timestamp=payload_timestamp,
                        )
                    )
                    await session.flush()

            result = await session.execute(
                select(Transaction)
                .where(Transaction.transaction_id == payload.transaction_id)
                .with_for_update()
            )
            transaction = result.scalar_one()
            current_created_at = _ensure_utc(transaction.created_at)
            current_last_event = _ensure_utc(transaction.last_event_timestamp)
            transaction.merchant_id = payload.merchant_id
            # Amount and currency are set once at initiation. Later events carry the same
            # values by convention; we do not overwrite to avoid silent financial mutations
            # from corrupted or replayed events with a different amount.
            if payload.event_type == EventType.PAYMENT_INITIATED:
                transaction.amount = payload.amount
                transaction.currency = payload.currency
            transaction.created_at = min(current_created_at, payload_timestamp)
            transaction.updated_at = now
            transaction.last_event_timestamp = max(current_last_event, payload_timestamp)

            conflict_detected = False
            if payload.event_type == EventType.PAYMENT_INITIATED:
                if transaction.payment_status != PaymentStatus.INITIATED or (
                    transaction.settlement_status != SettlementStatus.PENDING
                ):
                    conflict_detected = True
            elif payload.event_type == EventType.PAYMENT_PROCESSED:
                if transaction.payment_status == PaymentStatus.INITIATED:
                    transaction.payment_status = PaymentStatus.PROCESSED
                elif transaction.payment_status == PaymentStatus.FAILED:
                    conflict_detected = True
            elif payload.event_type == EventType.PAYMENT_FAILED:
                if transaction.payment_status == PaymentStatus.INITIATED:
                    transaction.payment_status = PaymentStatus.FAILED
                elif transaction.payment_status == PaymentStatus.PROCESSED:
                    conflict_detected = True
            elif payload.event_type == EventType.SETTLED:
                transaction.settlement_status = SettlementStatus.SETTLED
                # Settlement without any prior processing or failure is a conflicting
                # transition. Settlement after failure is a known discrepancy scenario
                # (settled_after_failure), not a state conflict, so we do not set
                # conflict_detected there — recompute_discrepancy handles it via its
                # SETTLED_AFTER_FAILURE check.
                if transaction.payment_status == PaymentStatus.INITIATED:
                    conflict_detected = True

            transaction.discrepancy_type = recompute_discrepancy(
                transaction, conflict_detected=conflict_detected
            )
            await session.flush()
    except IntegrityError:
        await session.rollback()
        transaction = await session.get(Transaction, payload.transaction_id)
        if transaction is None:  # pragma: no cover
            raise
        return EventIngestionResponse(
            ingestion_status="duplicate",
            transaction_id=transaction.transaction_id,
            payment_status=transaction.payment_status,
            settlement_status=transaction.settlement_status,
            status=derive_status(transaction.payment_status, transaction.settlement_status),
            discrepancy_type=transaction.discrepancy_type,
        )

    return await get_transaction_snapshot(session, payload.transaction_id)
