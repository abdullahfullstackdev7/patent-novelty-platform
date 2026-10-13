"""Business data: clients, plans, subscriptions, invoices and usage metering."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.platform import UUID_PK


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    segment: Mapped[str | None] = mapped_column(String(64))
    signed_up_on: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    included_reports: Mapped[int] = mapped_column(Integer, nullable=False)
    overage_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    seats: Mapped[int] = mapped_column(Integer, nullable=False)
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    ended_on: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'cancelled', 'paused')", name="status_valid"),
        Index("ix_subscriptions_client_id", "client_id"),
        Index("ix_subscriptions_plan_id", "plan_id"),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), nullable=False)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id"))
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    issued_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    paid_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'issued', 'paid', 'overdue', 'void')", name="status_valid"
        ),
        Index("ix_invoices_client_id", "client_id"),
        Index("ix_invoices_status_due_on", "status", "due_on"),
        Index("ix_invoices_period_start", "period_start"),
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('subscription', 'overage', 'addon')", name="kind_valid"),
        Index("ix_invoice_lines_invoice_id", "invoice_id"),
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    units: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="1")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_usage_events_client_id_occurred_at", "client_id", "occurred_at"),
        Index("ix_usage_events_event_type_occurred_at", "event_type", "occurred_at"),
    )
