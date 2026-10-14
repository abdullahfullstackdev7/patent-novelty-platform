"""Usage metering: one `report_generated` event per case, written when its report is first made."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.invoicing import REPORT_EVENT
from app.billing.subscriptions import active_subscription
from app.db.models import Case, UsageEvent


def record_report_generated(session: Session, case: Case) -> UsageEvent | None:
    """Meter the case once. Reruns and new report versions are not billed again.

    Cases of users without a client (the platform's own staff, demos of the product) are not
    metered. The plan on the event is the one active today, so overage can be traced to a plan.
    """
    if case.client_id is None:
        return None
    already = session.scalar(
        select(UsageEvent.id).where(
            UsageEvent.case_id == case.id, UsageEvent.event_type == REPORT_EVENT
        )
    )
    if already is not None:
        return None
    subscription = active_subscription(session, case.client_id, date.today())
    event = UsageEvent(
        client_id=case.client_id,
        case_id=case.id,
        plan_id=subscription.plan_id if subscription else None,
        event_type=REPORT_EVENT,
        units=1,
        is_demo=bool(case.is_demo),
    )
    session.add(event)
    session.flush()
    return event
