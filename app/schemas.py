from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import DiscrepancyType, EventType, PaymentStatus, SettlementStatus


def derive_status(
    payment_status: PaymentStatus, settlement_status: SettlementStatus
) -> Literal["failed", "settled", "processed_pending_settlement", "initiated"]:
    if payment_status == PaymentStatus.FAILED:
        return "failed"
    if (
        payment_status == PaymentStatus.PROCESSED
        and settlement_status == SettlementStatus.SETTLED
    ):
        return "settled"
    if payment_status == PaymentStatus.PROCESSED:
        return "processed_pending_settlement"
    return "initiated"


class EventIn(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    event_id: str = Field(min_length=1, max_length=64)
    event_type: EventType
    transaction_id: str = Field(min_length=1, max_length=64)
    merchant_id: str = Field(min_length=1, max_length=64)
    merchant_name: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    timestamp: datetime

    @field_validator("currency")
    @classmethod
    def currency_must_be_upper(cls, value: str) -> str:
        return value.upper()

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_not_be_future(cls, value: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        if value > now:
            raise ValueError("timestamp cannot be in the future")
        return value


class EventIngestionResponse(BaseModel):
    ingestion_status: Literal["accepted", "duplicate", "duplicate_with_conflict"]
    transaction_id: str
    payment_status: PaymentStatus
    settlement_status: SettlementStatus
    status: Literal["failed", "settled", "processed_pending_settlement", "initiated"]
    discrepancy_type: Optional[DiscrepancyType]


class MerchantOut(BaseModel):
    merchant_id: str
    merchant_name: str


class EventHistoryOut(BaseModel):
    event_id: str
    event_type: EventType
    timestamp: datetime
    amount: Decimal
    currency: str


class TransactionOut(BaseModel):
    transaction_id: str
    amount: Decimal
    currency: str
    payment_status: PaymentStatus
    settlement_status: SettlementStatus
    status: Literal["failed", "settled", "processed_pending_settlement", "initiated"]
    discrepancy_type: Optional[DiscrepancyType]
    created_at: datetime
    updated_at: datetime
    last_event_timestamp: datetime


class TransactionDetailsResponse(BaseModel):
    transaction: TransactionOut
    merchant: MerchantOut
    events: list[EventHistoryOut]


class PaginationMeta(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class TransactionListResponse(BaseModel):
    transactions: list[TransactionOut]
    pagination: PaginationMeta


class ReconciliationSummaryItem(BaseModel):
    group: str
    transaction_count: int
    total_amount: Decimal
    avg_amount: Decimal
    initiated_count: int
    processed_count: int
    settled_count: int
    failed_count: int
    discrepancy_count: int


class ReconciliationSummaryResponse(BaseModel):
    group_by: Literal["merchant", "date", "status"]
    summaries: list[ReconciliationSummaryItem]


class DiscrepancySummary(BaseModel):
    total: int
    by_type: dict[str, int]


class DiscrepancyRow(BaseModel):
    transaction_id: str
    merchant_id: str
    merchant_name: str
    amount: Decimal
    currency: str
    payment_status: PaymentStatus
    settlement_status: SettlementStatus
    status: Literal["failed", "settled", "processed_pending_settlement", "initiated"]
    discrepancy_type: DiscrepancyType
    description: str
    event_timeline: list[EventHistoryOut]


class ReconciliationDiscrepanciesResponse(BaseModel):
    discrepancies: list[DiscrepancyRow]
    summary: DiscrepancySummary
    pagination: PaginationMeta


class HealthResponse(BaseModel):
    status: str
    database: str
    event_count: int
    transaction_count: int
