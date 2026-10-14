"""Scheduled billing work for the worker: overdue sweep, monthly invoices, nightly view refresh.

Each task is idempotent and records when it last ran in app_settings, so several workers or a
restart never bill a month twice.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.billing import invoicing, views
from app.billing.subscriptions import previous_month
from app.config import Settings
from app.db.models import AppSetting

STATE_KEY = "billing_cycle"
REFRESH_HOUR_UTC = 2


def run_due(
    sessions: sessionmaker[Session], settings: Settings, now: datetime | None = None
) -> dict[str, object]:
    """Run whatever is due at `now`. Returns what was done, for logging and tests."""
    moment = now or datetime.now(UTC)
    today = moment.date()
    done: dict[str, object] = {}
    with sessions() as session:
        row = session.get(AppSetting, STATE_KEY)
        state = dict(row.value) if row else {}

        if state.get("last_overdue") != today.isoformat():
            done["overdue"] = invoicing.mark_overdue(session, today)
            state["last_overdue"] = today.isoformat()

        month = previous_month(today)
        if state.get("last_invoice_month") != f"{month:%Y-%m}":
            created = invoicing.generate_invoices(session, month)
            for invoice in created:
                invoicing.issue_invoice(session, settings, invoice, issued_on=today)
            done["invoices"] = len(created)
            state["last_invoice_month"] = f"{month:%Y-%m}"

        if (
            moment.hour >= REFRESH_HOUR_UTC and state.get("last_refresh") != today.isoformat()
        ) or done:
            views.refresh_views(session)
            state["last_refresh"] = today.isoformat()
            done["refreshed"] = True

        session.execute(
            insert(AppSetting)
            .values(key=STATE_KEY, value=state)
            .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": state})
        )
        session.commit()
    return done
