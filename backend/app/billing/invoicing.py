"""Invoice ledger: monthly generation, issuing, payment, voiding and the overdue sweep.

Revenue lines per invoice:
  subscription  the plan price for the month
  addon         seats above the plan's seat allowance, at the plan's extra seat price
  overage       reports above the plan's monthly allowance, at the overage price

There is no payment processor. Marking an invoice paid only records the date.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.subscriptions import BillingError, month_start, next_month
from app.config import Settings
from app.db.models import Invoice, InvoiceLine, Plan, Subscription, UsageEvent

CENT = Decimal("0.01")
REPORT_EVENT = "report_generated"
REVENUE_STATUSES = ("issued", "paid", "overdue")


def money(value: Decimal | float | int) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineDraft:
    kind: str
    description: str
    quantity: Decimal
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return money(self.quantity * self.unit_price)


def build_lines(plan: Plan, seats: int, reports_used: int, period: date) -> list[LineDraft]:
    """Invoice lines for one month. Pure, so the arithmetic is easy to test."""
    label = period.strftime("%B %Y")
    lines = [
        LineDraft(
            "subscription", f"{plan.name} plan, {label}", Decimal(1), money(plan.monthly_price)
        )
    ]
    extra_seats = max(seats - plan.seats, 0)
    if extra_seats and plan.extra_seat_price > 0:
        lines.append(
            LineDraft(
                "addon",
                f"Additional seats ({extra_seats}), {label}",
                Decimal(extra_seats),
                money(plan.extra_seat_price),
            )  # fmt: skip
        )
    overage = max(reports_used - plan.included_reports, 0)
    if overage:
        lines.append(
            LineDraft(
                "overage",
                f"Reports above the {plan.included_reports} included ({reports_used} used), {label}",
                Decimal(overage),
                money(plan.overage_price),
            )  # fmt: skip
        )
    return lines


def reports_in_month(session: Session, client_id: uuid.UUID, period: date) -> int:
    start, end = month_start(period), next_month(period)
    total = session.scalar(
        select(func.coalesce(func.sum(UsageEvent.units), 0)).where(
            UsageEvent.client_id == client_id,
            UsageEvent.event_type == REPORT_EVENT,
            UsageEvent.occurred_at >= start,
            UsageEvent.occurred_at < end,
        )
    )
    return int(total or 0)


def _next_number(session: Session, period: date) -> str:
    prefix = f"INV-{period:%Y%m}-"
    existing = session.scalar(
        select(func.count()).select_from(Invoice).where(Invoice.number.like(prefix + "%"))
    )
    return f"{prefix}{(existing or 0) + 1:04d}"


def _has_invoice(session: Session, client_id: uuid.UUID, period_start: date) -> bool:
    return (
        session.scalar(
            select(Invoice.id).where(
                Invoice.client_id == client_id,
                Invoice.period_start == period_start,
                Invoice.status != "void",
            )
        )
        is not None
    )


def generate_invoices(
    session: Session, period: date, *, client_id: uuid.UUID | None = None
) -> list[Invoice]:
    """Draft invoices for every client with an active subscription at the end of `period`'s month.

    Idempotent: a client that already has a non-void invoice for the month is skipped.
    """
    start, end_exclusive = month_start(period), next_month(period)
    last_day = end_exclusive - timedelta(days=1)
    query = select(Subscription).where(
        Subscription.started_on <= last_day,
        (Subscription.ended_on.is_(None)) | (Subscription.ended_on > last_day),
    )
    if client_id is not None:
        query = query.where(Subscription.client_id == client_id)
    created: list[Invoice] = []
    for subscription in session.scalars(query.order_by(Subscription.client_id)):
        if _has_invoice(session, subscription.client_id, start):
            continue
        plan = session.get(Plan, subscription.plan_id)
        used = reports_in_month(session, subscription.client_id, start)
        invoice = Invoice(
            number=_next_number(session, start),
            client_id=subscription.client_id,
            subscription_id=subscription.id,
            period_start=start,
            period_end=last_day,
            status="draft",
        )
        session.add(invoice)
        session.flush()
        total = Decimal(0)
        for line in build_lines(plan, subscription.seats, used, start):
            session.add(
                InvoiceLine(
                    invoice_id=invoice.id,
                    kind=line.kind,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    amount=line.amount,
                )  # fmt: skip
            )
            total += line.amount
        invoice.total = money(total)
        created.append(invoice)
    session.flush()
    return created


def issue_invoice(
    session: Session, settings: Settings, invoice: Invoice, issued_on: date | None = None
) -> Invoice:
    if invoice.status != "draft":
        raise BillingError(f"Only a draft invoice can be issued, this one is {invoice.status}")
    day = issued_on or date.today()
    invoice.issued_on = day
    invoice.due_on = day + timedelta(days=settings.invoice_due_days)
    invoice.status = "issued"
    session.flush()
    return invoice


def mark_paid(session: Session, invoice: Invoice, paid_on: date | None = None) -> Invoice:
    if invoice.status not in ("issued", "overdue"):
        raise BillingError(
            f"Only an issued or overdue invoice can be paid, this one is {invoice.status}"
        )
    day = paid_on or date.today()
    if invoice.issued_on and day < invoice.issued_on:
        raise BillingError("An invoice cannot be paid before it was issued")
    invoice.paid_on = day
    invoice.status = "paid"
    session.flush()
    return invoice


def void_invoice(session: Session, invoice: Invoice) -> Invoice:
    if invoice.status == "paid":
        raise BillingError("A paid invoice cannot be voided")
    if invoice.status == "void":
        raise BillingError("The invoice is already void")
    invoice.status = "void"
    session.flush()
    return invoice


def mark_overdue(session: Session, today: date | None = None) -> int:
    """Issued invoices past their due date become overdue. Returns how many changed."""
    day = today or date.today()
    changed = 0
    for invoice in session.scalars(
        select(Invoice).where(Invoice.status == "issued", Invoice.due_on < day)
    ):
        invoice.status = "overdue"
        changed += 1
    session.flush()
    return changed


def invoice_matches_lines(session: Session, invoice: Invoice) -> bool:
    """Ledger invariant: the invoice total equals the sum of its lines."""
    total = session.scalar(
        select(func.coalesce(func.sum(InvoiceLine.amount), 0)).where(
            InvoiceLine.invoice_id == invoice.id
        )
    )
    return money(total) == money(invoice.total)
