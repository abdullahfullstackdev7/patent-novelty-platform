"""Admin billing: clients, subscriptions, invoices and the analytics view refresh."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text, true

from app.api.deps import SessionDep, SettingsDep, ip_of, require
from app.billing import invoicing, subscriptions, views
from app.billing.subscriptions import BillingError
from app.db.models import Client, Invoice, InvoiceLine, Plan, Subscription
from app.security import policy
from app.services import audit

router = APIRouter(prefix="/billing", tags=["billing"])
AdminDep = Depends(require(policy.can_manage_billing))


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientIn(StrictBody):
    name: str = Field(min_length=1, max_length=200)
    industry: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)
    segment: str | None = Field(default=None, max_length=64)


class SubscriptionIn(StrictBody):
    plan_code: str = Field(min_length=1, max_length=32)
    seats: int | None = Field(default=None, ge=1, le=10_000)
    effective: date | None = None


class GenerateIn(StrictBody):
    month: date = Field(description="Any day of the month to bill")


class IssueIn(StrictBody):
    issued_on: date | None = None


class PayIn(StrictBody):
    paid_on: date | None = None


def _billing_error(error: BillingError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


def _client_or_404(session, client_id: uuid.UUID) -> Client:
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return client


def _invoice_or_404(session, invoice_id: uuid.UUID) -> Invoice:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return invoice


def _invoice_out(invoice: Invoice, client_name: str | None = None) -> dict[str, Any]:
    return {
        "id": invoice.id, "number": invoice.number, "client_id": invoice.client_id, "client_name": client_name,
        "period_start": invoice.period_start, "period_end": invoice.period_end, "issued_on": invoice.issued_on,
        "due_on": invoice.due_on, "paid_on": invoice.paid_on, "status": invoice.status,
        "total": float(invoice.total),
    }  # fmt: skip


def _refresh(session) -> None:
    views.refresh_views(session)


# ---- clients ------------------------------------------------------------------------------------


@router.get("/clients")
def list_clients(
    session: SessionDep,
    _=AdminDep,
    include_demo: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Clients with their current plan, MRR and reports used this month."""
    sql = """
    SELECT c.id, c.name, c.industry, c.region, c.segment, c.is_demo, c.signed_up_on,
           p.code AS plan_code, s.seats,
           (p.monthly_price + greatest(s.seats - p.seats, 0) * p.extra_seat_price) AS mrr,
           p.included_reports,
           (SELECT COALESCE(sum(u.units), 0) FROM usage_events u WHERE u.client_id = c.id
              AND u.event_type = 'report_generated' AND u.occurred_at >= date_trunc('month', now())) AS reports_this_month
    FROM clients c
    LEFT JOIN LATERAL (
        SELECT * FROM subscriptions s WHERE s.client_id = c.id AND s.started_on <= current_date
           AND (s.ended_on IS NULL OR s.ended_on > current_date) ORDER BY s.started_on DESC LIMIT 1) s ON true
    LEFT JOIN plans p ON p.id = s.plan_id
    WHERE (:include_demo OR NOT c.is_demo)
    ORDER BY c.name LIMIT :limit OFFSET :offset"""
    found = (
        session.execute(text(sql), {"include_demo": include_demo, "limit": limit, "offset": offset})
        .mappings()
        .all()
    )
    total = session.scalar(
        select(func.count())
        .select_from(Client)
        .where(true() if include_demo else Client.is_demo.is_(False))
    )
    items = [
        {k: (float(v) if hasattr(v, "quantize") else v) for k, v in row.items()} for row in found
    ]
    return {"items": items, "total": total}


@router.post("/clients", status_code=status.HTTP_201_CREATED)
def create_client(
    request: Request, body: ClientIn, session: SessionDep, admin=AdminDep
) -> dict[str, Any]:
    client = Client(
        name=body.name, industry=body.industry, region=body.region, segment=body.segment
    )
    session.add(client)
    session.flush()
    audit.record(session, audit.BILLING_CLIENT_CREATE, user_id=admin.id, ip=ip_of(request),
                 entity_type="client", entity_id=client.id)  # fmt: skip
    session.commit()
    return {"id": client.id, "name": client.name, "industry": client.industry, "region": client.region,
            "segment": client.segment, "is_demo": client.is_demo}  # fmt: skip


@router.get("/clients/{client_id}")
def get_client(client_id: uuid.UUID, session: SessionDep, _=AdminDep) -> dict[str, Any]:
    client = _client_or_404(session, client_id)
    history = session.execute(
        select(Subscription, Plan).join(Plan, Plan.id == Subscription.plan_id)
        .where(Subscription.client_id == client_id).order_by(Subscription.started_on.desc())
    ).all()  # fmt: skip
    invoices = session.scalars(
        select(Invoice)
        .where(Invoice.client_id == client_id)
        .order_by(Invoice.period_start.desc())
        .limit(12)
    ).all()
    usage = (
        session.execute(
            text("""SELECT date_trunc('month', occurred_at)::date AS month, sum(units) AS reports FROM usage_events
                WHERE client_id = :c AND event_type = 'report_generated' AND occurred_at >= now() - interval '6 months'
                GROUP BY 1 ORDER BY 1"""),
            {"c": client_id},
        )
        .mappings()
        .all()
    )
    return {
        "client": {
            "id": client.id,
            "name": client.name,
            "industry": client.industry,
            "region": client.region,
            "segment": client.segment,
            "is_demo": client.is_demo,
            "signed_up_on": client.signed_up_on,
        },  # fmt: skip
        "subscriptions": [
            {
                "id": s.id,
                "plan": p.code,
                "seats": s.seats,
                "started_on": s.started_on,
                "ended_on": s.ended_on,
                "status": s.status,
            }
            for s, p in history
        ],  # fmt: skip
        "invoices": [_invoice_out(i, client.name) for i in invoices],
        "usage": [{"month": r["month"], "reports": float(r["reports"])} for r in usage],
    }


@router.put("/clients/{client_id}/subscription")
def set_subscription(
    client_id: uuid.UUID,
    request: Request,
    body: SubscriptionIn,
    session: SessionDep,
    admin=AdminDep,
) -> dict[str, Any]:
    """Start or change a plan from the first of the month (an upgrade, downgrade or seat change)."""
    _client_or_404(session, client_id)
    try:
        sub = subscriptions.change_subscription(
            session, client_id, body.plan_code, body.seats, body.effective or date.today()
        )
    except BillingError as error:
        raise _billing_error(error) from None
    audit.record(session, audit.SUBSCRIPTION_CHANGE, user_id=admin.id, ip=ip_of(request), entity_type="client",
                 entity_id=client_id, detail={"plan": body.plan_code, "seats": sub.seats})  # fmt: skip
    _refresh(session)
    session.commit()
    return {
        "id": sub.id,
        "plan": body.plan_code,
        "seats": sub.seats,
        "started_on": sub.started_on,
        "ended_on": sub.ended_on,
    }


@router.delete("/clients/{client_id}/subscription")
def cancel_subscription(
    client_id: uuid.UUID, request: Request, session: SessionDep, admin=AdminDep,
    effective: date | None = None,
) -> dict[str, Any]:  # fmt: skip
    """End the subscription after the month of `effective`. That month is still billed."""
    _client_or_404(session, client_id)
    try:
        sub = subscriptions.cancel_subscription(session, client_id, effective or date.today())
    except BillingError as error:
        raise _billing_error(error) from None
    audit.record(session, audit.SUBSCRIPTION_CANCEL, user_id=admin.id, ip=ip_of(request), entity_type="client",
                 entity_id=client_id)  # fmt: skip
    _refresh(session)
    session.commit()
    return {"id": sub.id, "ended_on": sub.ended_on, "status": sub.status}


# ---- invoices -------------------------------------------------------------------------------------


@router.get("/invoices")
def list_invoices(
    session: SessionDep,
    _=AdminDep,
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(draft|issued|paid|overdue|void)$"
    ),
    client_id: uuid.UUID | None = None,
    include_demo: bool = True,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    query = select(Invoice, Client.name).join(Client, Client.id == Invoice.client_id)
    if status_filter:
        query = query.where(Invoice.status == status_filter)
    if client_id:
        query = query.where(Invoice.client_id == client_id)
    if not include_demo:
        query = query.where(Client.is_demo.is_(False))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    found = session.execute(
        query.order_by(Invoice.period_start.desc(), Invoice.number).limit(limit).offset(offset)
    ).all()
    return {"items": [_invoice_out(i, name) for i, name in found], "total": total}


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: uuid.UUID, session: SessionDep, _=AdminDep) -> dict[str, Any]:
    invoice = _invoice_or_404(session, invoice_id)
    lines = session.scalars(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.id)
    ).all()
    return {
        **_invoice_out(invoice, session.get(Client, invoice.client_id).name),
        "lines": [
            {
                "kind": ln.kind,
                "description": ln.description,
                "quantity": float(ln.quantity),
                "unit_price": float(ln.unit_price),
                "amount": float(ln.amount),
            }
            for ln in lines
        ],  # fmt: skip
        "balanced": invoicing.invoice_matches_lines(session, invoice),
    }


@router.post("/invoices/generate", status_code=status.HTTP_201_CREATED)
def generate_invoices(
    request: Request, body: GenerateIn, session: SessionDep, admin=AdminDep
) -> dict[str, Any]:
    """Draft invoices for the month: subscription, extra seats and overage. Idempotent."""
    created = invoicing.generate_invoices(session, body.month)
    audit.record(session, audit.INVOICES_GENERATED, user_id=admin.id, ip=ip_of(request),
                 detail={"month": body.month.strftime("%Y-%m"), "count": len(created)})  # fmt: skip
    session.commit()
    return {
        "month": body.month.replace(day=1),
        "created": len(created),
        "invoices": [_invoice_out(i) for i in created],
    }


@router.post("/invoices/mark-overdue")
def mark_overdue(session: SessionDep, _=AdminDep) -> dict[str, int]:
    changed = invoicing.mark_overdue(session)
    _refresh(session)
    session.commit()
    return {"changed": changed}


def _transition(request, session, admin, invoice_id, action: str, **kwargs):
    invoice = _invoice_or_404(session, invoice_id)
    settings = request.app.state.settings
    try:
        if action == "issue":
            invoicing.issue_invoice(session, settings, invoice, kwargs.get("day"))
            event = audit.INVOICE_ISSUED
        elif action == "pay":
            invoicing.mark_paid(session, invoice, kwargs.get("day"))
            event = audit.INVOICE_PAID
        else:
            invoicing.void_invoice(session, invoice)
            event = audit.INVOICE_VOIDED
    except BillingError as error:
        raise _billing_error(error) from None
    audit.record(session, event, user_id=admin.id, ip=ip_of(request), entity_type="invoice", entity_id=invoice_id,
                 detail={"number": invoice.number})  # fmt: skip
    _refresh(session)
    session.commit()
    return _invoice_out(invoice)


@router.post("/invoices/{invoice_id}/issue")
def issue_invoice(
    invoice_id: uuid.UUID, request: Request, body: IssueIn, session: SessionDep, admin=AdminDep
):
    return _transition(request, session, admin, invoice_id, "issue", day=body.issued_on)


@router.post("/invoices/{invoice_id}/pay")
def pay_invoice(
    invoice_id: uuid.UUID, request: Request, body: PayIn, session: SessionDep, admin=AdminDep
):
    return _transition(request, session, admin, invoice_id, "pay", day=body.paid_on)


@router.post("/invoices/{invoice_id}/void")
def void_invoice(invoice_id: uuid.UUID, request: Request, session: SessionDep, admin=AdminDep):
    return _transition(request, session, admin, invoice_id, "void")


# ---- views ------------------------------------------------------------------------------------------


@router.post("/refresh")
def refresh(
    request: Request, session: SessionDep, settings: SettingsDep, admin=AdminDep
) -> dict[str, Any]:
    """Rebuild the revenue analytics views now (they are also rebuilt nightly)."""
    moment = views.refresh_views(session)
    audit.record(session, audit.BILLING_REFRESH, user_id=admin.id, ip=ip_of(request))
    session.commit()
    return {"refreshed_at": moment}
