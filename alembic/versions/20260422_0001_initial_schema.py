"""initial schema

Revision ID: 20260422_0001
Revises: None
Create Date: 2026-04-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PgEnum


revision = "20260422_0001"
down_revision = None
branch_labels = None
depends_on = None

# PgEnum with create_type=False: types are created idempotently via DO blocks
# below; SQLAlchemy must not attempt a second CREATE TYPE during op.create_table.
# Using PgEnum (not sa.Enum) ensures create_type=False is read by the concrete
# _on_table_create implementation rather than being lost in the Emulated wrapper.
payment_status = PgEnum("INITIATED", "PROCESSED", "FAILED", name="paymentstatus", create_type=False)
settlement_status = PgEnum("PENDING", "SETTLED", name="settlementstatus", create_type=False)
event_type = PgEnum(
    "PAYMENT_INITIATED",
    "PAYMENT_PROCESSED",
    "PAYMENT_FAILED",
    "SETTLED",
    name="eventtype",
    create_type=False,
)
discrepancy_type = PgEnum(
    "PROCESSED_NOT_SETTLED",
    "SETTLED_AFTER_FAILURE",
    "CONFLICTING_STATE_TRANSITION",
    name="discrepancytype",
    create_type=False,
)

# SQLite fallback types for tests that run against SQLite
_payment_status_sqlite = sa.Enum("INITIATED", "PROCESSED", "FAILED", name="paymentstatus")
_settlement_status_sqlite = sa.Enum("PENDING", "SETTLED", name="settlementstatus")
_event_type_sqlite = sa.Enum(
    "PAYMENT_INITIATED", "PAYMENT_PROCESSED", "PAYMENT_FAILED", "SETTLED", name="eventtype"
)
_discrepancy_type_sqlite = sa.Enum(
    "PROCESSED_NOT_SETTLED", "SETTLED_AFTER_FAILURE", "CONFLICTING_STATE_TRANSITION",
    name="discrepancytype",
)


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("""
            DO $$ BEGIN
                CREATE TYPE paymentstatus AS ENUM ('INITIATED', 'PROCESSED', 'FAILED');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
        op.execute("""
            DO $$ BEGIN
                CREATE TYPE settlementstatus AS ENUM ('PENDING', 'SETTLED');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
        op.execute("""
            DO $$ BEGIN
                CREATE TYPE eventtype AS ENUM (
                    'PAYMENT_INITIATED', 'PAYMENT_PROCESSED', 'PAYMENT_FAILED', 'SETTLED'
                );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
        op.execute("""
            DO $$ BEGIN
                CREATE TYPE discrepancytype AS ENUM (
                    'PROCESSED_NOT_SETTLED', 'SETTLED_AFTER_FAILURE', 'CONFLICTING_STATE_TRANSITION'
                );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)

    ps = payment_status if is_pg else _payment_status_sqlite
    ss = settlement_status if is_pg else _settlement_status_sqlite
    et = event_type if is_pg else _event_type_sqlite
    dt = discrepancy_type if is_pg else _discrepancy_type_sqlite

    op.create_table(
        "merchants",
        sa.Column("merchant_id", sa.String(length=64), primary_key=True),
        sa.Column("merchant_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "transactions",
        sa.Column("transaction_id", sa.String(length=64), primary_key=True),
        sa.Column("merchant_id", sa.String(length=64), sa.ForeignKey("merchants.merchant_id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payment_status", ps, nullable=False),
        sa.Column("settlement_status", ss, nullable=False),
        sa.Column("discrepancy_type", dt, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.String(length=64),
            sa.ForeignKey(
                "transactions.transaction_id",
                deferrable=True,
                initially="DEFERRED",
            ),
            nullable=False,
        ),
        sa.Column("merchant_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", et, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_events_transaction_timestamp",
        "events",
        ["transaction_id", "event_timestamp"],
    )
    op.create_index(
        "idx_transactions_merchant_created",
        "transactions",
        ["merchant_id", "created_at"],
    )
    op.create_index(
        "idx_transactions_status_created",
        "transactions",
        ["payment_status", "settlement_status", "created_at"],
    )
    op.create_index("idx_transactions_created", "transactions", ["created_at"])
    if is_pg:
        op.execute(
            "CREATE INDEX idx_transactions_discrepancy ON transactions (discrepancy_type) "
            "WHERE discrepancy_type IS NOT NULL"
        )
    else:
        op.create_index("idx_transactions_discrepancy", "transactions", ["discrepancy_type"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("idx_transactions_discrepancy", table_name="transactions")
    op.drop_index("idx_transactions_created", table_name="transactions")
    op.drop_index("idx_transactions_status_created", table_name="transactions")
    op.drop_index("idx_transactions_merchant_created", table_name="transactions")
    op.drop_index("idx_events_transaction_timestamp", table_name="events")
    op.drop_table("events")
    op.drop_table("transactions")
    op.drop_table("merchants")

    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS discrepancytype")
        op.execute("DROP TYPE IF EXISTS eventtype")
        op.execute("DROP TYPE IF EXISTS settlementstatus")
        op.execute("DROP TYPE IF EXISTS paymentstatus")
