from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EventType(str, Enum):
    PAYMENT_INITIATED = "payment_initiated"
    PAYMENT_PROCESSED = "payment_processed"
    PAYMENT_FAILED = "payment_failed"
    SETTLED = "settled"


class PaymentStatus(str, Enum):
    INITIATED = "initiated"
    PROCESSED = "processed"
    FAILED = "failed"


class SettlementStatus(str, Enum):
    PENDING = "pending"
    SETTLED = "settled"


class DiscrepancyType(str, Enum):
    PROCESSED_NOT_SETTLED = "processed_not_settled"
    SETTLED_AFTER_FAILURE = "settled_after_failure"
    CONFLICTING_STATE_TRANSITION = "conflicting_state_transition"


class Merchant(Base):
    __tablename__ = "merchants"

    merchant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    merchant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="merchant")


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchants.merchant_id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_status: Mapped[PaymentStatus] = mapped_column(
        SqlEnum(PaymentStatus), nullable=False
    )
    settlement_status: Mapped[SettlementStatus] = mapped_column(
        SqlEnum(SettlementStatus), nullable=False
    )
    discrepancy_type: Mapped[Optional[DiscrepancyType]] = mapped_column(
        SqlEnum(DiscrepancyType), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    merchant: Mapped[Merchant] = relationship(back_populates="transactions")
    events: Mapped[list["Event"]] = relationship(back_populates="transaction")


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "transactions.transaction_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    merchant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[EventType] = mapped_column(SqlEnum(EventType), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    transaction: Mapped[Transaction] = relationship(back_populates="events")


Index("idx_events_transaction_timestamp", Event.transaction_id, Event.event_timestamp.desc())
Index("idx_transactions_merchant_created", Transaction.merchant_id, Transaction.created_at.desc())
Index(
    "idx_transactions_status_created",
    Transaction.payment_status,
    Transaction.settlement_status,
    Transaction.created_at.desc(),
)
Index("idx_transactions_created", Transaction.created_at.desc())
Index(
    "idx_transactions_discrepancy",
    Transaction.discrepancy_type,
    postgresql_where=Transaction.discrepancy_type.is_not(None),
)
