from collections import defaultdict
from math import ceil
from typing import Optional

from sqlalchemy import String, case, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import DiscrepancyType, Event, Merchant, PaymentStatus, SettlementStatus, Transaction
from app.schemas import (
    DiscrepancyRow,
    DiscrepancySummary,
    EventHistoryOut,
    MerchantOut,
    PaginationMeta,
    ReconciliationDiscrepanciesResponse,
    ReconciliationSummaryItem,
    ReconciliationSummaryResponse,
    TransactionDetailsResponse,
    TransactionListResponse,
    TransactionOut,
    derive_status,
)
from app.services.event_ingestion import describe_discrepancy


STATUS_CASE = case(
    (
        Transaction.payment_status == PaymentStatus.FAILED,
        "failed",
    ),
    (
        (Transaction.payment_status == PaymentStatus.PROCESSED)
        & (Transaction.settlement_status == SettlementStatus.SETTLED),
        "settled",
    ),
    (
        Transaction.payment_status == PaymentStatus.PROCESSED,
        "processed_pending_settlement",
    ),
    else_="initiated",
)


def _pagination(page: int, per_page: int, total: int) -> PaginationMeta:
    return PaginationMeta(
        page=page,
        per_page=per_page,
        total=total,
        total_pages=max(1, ceil(total / per_page)) if per_page else 1,
    )


async def list_transactions(
    session: AsyncSession,
    *,
    merchant_id: Optional[str],
    status: Optional[str],
    start_date,
    end_date,
    page: int,
    per_page: int,
    sort_by: str,
    sort_order: str,
) -> TransactionListResponse:
    stmt = select(Transaction)
    count_stmt = select(func.count(Transaction.transaction_id))

    if merchant_id:
        stmt = stmt.where(Transaction.merchant_id == merchant_id)
        count_stmt = count_stmt.where(Transaction.merchant_id == merchant_id)
    if start_date:
        stmt = stmt.where(Transaction.created_at >= start_date)
        count_stmt = count_stmt.where(Transaction.created_at >= start_date)
    if end_date:
        stmt = stmt.where(Transaction.created_at <= end_date)
        count_stmt = count_stmt.where(Transaction.created_at <= end_date)
    if status:
        stmt = stmt.where(STATUS_CASE == status)
        count_stmt = count_stmt.where(STATUS_CASE == status)

    sort_map = {
        "created_at": Transaction.created_at,
        "amount": Transaction.amount,
        "status": STATUS_CASE,
    }
    sort_column = sort_map[sort_by]
    ordering = desc(sort_column) if sort_order == "desc" else sort_column

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(ordering).offset((page - 1) * per_page).limit(per_page)
    transactions = (await session.execute(stmt)).scalars().all()

    return TransactionListResponse(
        transactions=[
            TransactionOut(
                transaction_id=txn.transaction_id,
                amount=txn.amount,
                currency=txn.currency,
                payment_status=txn.payment_status,
                settlement_status=txn.settlement_status,
                status=derive_status(txn.payment_status, txn.settlement_status),
                discrepancy_type=txn.discrepancy_type,
                created_at=txn.created_at,
                updated_at=txn.updated_at,
                last_event_timestamp=txn.last_event_timestamp,
            )
            for txn in transactions
        ],
        pagination=_pagination(page, per_page, total),
    )


async def get_transaction_details(
    session: AsyncSession, transaction_id: str
) -> Optional[TransactionDetailsResponse]:
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.merchant), selectinload(Transaction.events))
        .where(Transaction.transaction_id == transaction_id)
    )
    transaction = (await session.execute(stmt)).scalar_one_or_none()
    if transaction is None:
        return None

    ordered_events = sorted(transaction.events, key=lambda event: event.event_timestamp)
    return TransactionDetailsResponse(
        transaction=TransactionOut(
            transaction_id=transaction.transaction_id,
            amount=transaction.amount,
            currency=transaction.currency,
            payment_status=transaction.payment_status,
            settlement_status=transaction.settlement_status,
            status=derive_status(transaction.payment_status, transaction.settlement_status),
            discrepancy_type=transaction.discrepancy_type,
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
            last_event_timestamp=transaction.last_event_timestamp,
        ),
        merchant=MerchantOut(
            merchant_id=transaction.merchant.merchant_id,
            merchant_name=transaction.merchant.merchant_name,
        ),
        events=[
            EventHistoryOut(
                event_id=event.event_id,
                event_type=event.event_type,
                timestamp=event.event_timestamp,
                amount=event.amount,
                currency=event.currency,
            )
            for event in ordered_events
        ],
    )


async def reconciliation_summary(
    session: AsyncSession,
    *,
    group_by: str,
    merchant_id: Optional[str],
    start_date,
    end_date,
) -> ReconciliationSummaryResponse:
    if group_by == "merchant":
        group_expr = Transaction.merchant_id
    elif group_by == "date":
        group_expr = cast(func.date(Transaction.created_at), String)
    else:
        group_expr = STATUS_CASE

    # Use conditional aggregation (CASE WHEN) — equivalent to FILTER(WHERE) on PostgreSQL,
    # and supported on SQLite via case(). Each count skips NULL, matching only the condition.
    stmt = select(
        group_expr.label("group_value"),
        func.count(Transaction.transaction_id).label("transaction_count"),
        func.sum(Transaction.amount).label("total_amount"),
        func.avg(Transaction.amount).label("avg_amount"),
        func.count(case((STATUS_CASE == "initiated", 1))).label("initiated_count"),
        func.count(case((STATUS_CASE == "processed_pending_settlement", 1))).label("processed_count"),
        func.count(case((STATUS_CASE == "settled", 1))).label("settled_count"),
        func.count(case((STATUS_CASE == "failed", 1))).label("failed_count"),
        func.count(case((Transaction.discrepancy_type.is_not(None), 1))).label("discrepancy_count"),
    ).group_by(group_expr)

    if merchant_id:
        stmt = stmt.where(Transaction.merchant_id == merchant_id)
    if start_date:
        stmt = stmt.where(Transaction.created_at >= start_date)
    if end_date:
        stmt = stmt.where(Transaction.created_at <= end_date)

    rows = (await session.execute(stmt.order_by("group_value"))).all()
    return ReconciliationSummaryResponse(
        group_by=group_by,
        summaries=[
            ReconciliationSummaryItem(
                group=str(row.group_value),
                transaction_count=row.transaction_count,
                total_amount=row.total_amount,
                avg_amount=row.avg_amount,
                initiated_count=row.initiated_count,
                processed_count=row.processed_count,
                settled_count=row.settled_count,
                failed_count=row.failed_count,
                discrepancy_count=row.discrepancy_count,
            )
            for row in rows
        ],
    )


async def discrepancy_report(
    session: AsyncSession,
    *,
    discrepancy_type: Optional[str],
    merchant_id: Optional[str],
    page: int,
    per_page: int,
) -> ReconciliationDiscrepanciesResponse:
    base_filter = Transaction.discrepancy_type.is_not(None)
    stmt = (
        select(Transaction, Merchant)
        .join(Merchant, Merchant.merchant_id == Transaction.merchant_id)
        .where(base_filter)
    )
    count_stmt = select(func.count(Transaction.transaction_id)).where(base_filter)

    if discrepancy_type:
        stmt = stmt.where(Transaction.discrepancy_type == discrepancy_type)
        count_stmt = count_stmt.where(Transaction.discrepancy_type == discrepancy_type)
    if merchant_id:
        stmt = stmt.where(Transaction.merchant_id == merchant_id)
        count_stmt = count_stmt.where(Transaction.merchant_id == merchant_id)

    total = (await session.execute(count_stmt)).scalar_one()

    # by_type breakdown is always over ALL discrepancy types (not filtered by type param)
    # so ops can see the global distribution even when drilling into one type.
    by_type_stmt = (
        select(Transaction.discrepancy_type, func.count(Transaction.transaction_id))
        .where(base_filter)
        .group_by(Transaction.discrepancy_type)
    )
    if merchant_id:
        by_type_stmt = by_type_stmt.where(Transaction.merchant_id == merchant_id)

    by_type_rows = (await session.execute(by_type_stmt)).all()
    by_type: dict[str, int] = {
        (row[0].value if hasattr(row[0], "value") else str(row[0])): row[1]
        for row in by_type_rows
    }

    rows = (
        await session.execute(
            stmt.order_by(Transaction.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).all()

    timeline_map: dict[str, list[EventHistoryOut]] = defaultdict(list)
    transaction_ids = [txn.transaction_id for txn, _ in rows]
    if transaction_ids:
        events_result = await session.execute(
            select(Event)
            .where(Event.transaction_id.in_(transaction_ids))
            .order_by(Event.transaction_id, Event.event_timestamp)
        )
        for event in events_result.scalars():
            timeline_map[event.transaction_id].append(
                EventHistoryOut(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    timestamp=event.event_timestamp,
                    amount=event.amount,
                    currency=event.currency,
                )
            )

    return ReconciliationDiscrepanciesResponse(
        discrepancies=[
            DiscrepancyRow(
                transaction_id=txn.transaction_id,
                merchant_id=merchant.merchant_id,
                merchant_name=merchant.merchant_name,
                amount=txn.amount,
                currency=txn.currency,
                payment_status=txn.payment_status,
                settlement_status=txn.settlement_status,
                status=derive_status(txn.payment_status, txn.settlement_status),
                discrepancy_type=txn.discrepancy_type,
                description=describe_discrepancy(txn.discrepancy_type) or "",
                event_timeline=timeline_map[txn.transaction_id],
            )
            for txn, merchant in rows
        ],
        summary=DiscrepancySummary(total=total, by_type=by_type),
        pagination=_pagination(page, per_page, total),
    )
