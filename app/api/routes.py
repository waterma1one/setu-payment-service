from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Event, Transaction
from app.schemas import (
    EventIn,
    EventIngestionResponse,
    HealthResponse,
    ReconciliationDiscrepanciesResponse,
    ReconciliationSummaryResponse,
    TransactionDetailsResponse,
    TransactionListResponse,
)
from app.services.event_ingestion import ingest_event
from app.services.reconciliation import (
    discrepancy_report,
    get_transaction_details,
    list_transactions,
    reconciliation_summary,
)

router = APIRouter()


@router.post("/events", response_model=EventIngestionResponse)
async def post_event(
    payload: EventIn, session: AsyncSession = Depends(get_session)
) -> EventIngestionResponse:
    return await ingest_event(session, payload)


@router.get("/transactions", response_model=TransactionListResponse)
async def get_transactions(
    merchant_id: Optional[str] = None,
    status: Optional[str] = Query(default=None, pattern="^(failed|settled|processed_pending_settlement|initiated)$"),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="created_at", pattern="^(created_at|amount|status)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    session: AsyncSession = Depends(get_session),
) -> TransactionListResponse:
    return await list_transactions(
        session,
        merchant_id=merchant_id,
        status=status,
        start_date=start_date,
        end_date=end_date,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/transactions/{transaction_id}", response_model=TransactionDetailsResponse)
async def get_transaction(
    transaction_id: str, session: AsyncSession = Depends(get_session)
) -> TransactionDetailsResponse:
    result = await get_transaction_details(session, transaction_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return result


@router.get("/reconciliation/summary", response_model=ReconciliationSummaryResponse)
async def get_reconciliation_summary(
    group_by: str = Query(pattern="^(merchant|date|status)$"),
    merchant_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    session: AsyncSession = Depends(get_session),
) -> ReconciliationSummaryResponse:
    return await reconciliation_summary(
        session,
        group_by=group_by,
        merchant_id=merchant_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/reconciliation/discrepancies",
    response_model=ReconciliationDiscrepanciesResponse,
)
async def get_reconciliation_discrepancies(
    type: Optional[str] = Query(
        default=None,
        pattern="^(processed_not_settled|settled_after_failure|conflicting_state_transition)$",
    ),
    merchant_id: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> ReconciliationDiscrepanciesResponse:
    return await discrepancy_report(
        session,
        discrepancy_type=type,
        merchant_id=merchant_id,
        page=page,
        per_page=per_page,
    )


@router.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
        event_count = (await session.execute(select(func.count(Event.event_id)))).scalar_one()
        transaction_count = (
            await session.execute(select(func.count(Transaction.transaction_id)))
        ).scalar_one()
        return HealthResponse(
            status="healthy",
            database="connected",
            event_count=event_count,
            transaction_count=transaction_count,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
