"""Materialized views behind the revenue analytics: refresh on demand and nightly."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import AppSetting

# Dependency order: the series is built from the monthly MRR view.
VIEWS = ("mv_client_month_mrr", "mv_client_mrr_series", "mv_client_revenue_month")
SETTING_KEY = "billing_views"


def refresh_views(session: Session) -> datetime:
    """Rebuild all views and remember when. The data is small, so a plain refresh is enough."""
    for view in VIEWS:
        session.execute(text(f"REFRESH MATERIALIZED VIEW {view}"))
    moment = datetime.now(UTC)
    values = {"refreshed_at": moment.isoformat()}
    session.execute(
        insert(AppSetting)
        .values(key=SETTING_KEY, value=values)
        .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": values})
    )
    return moment


def last_refreshed(session: Session) -> datetime | None:
    row = session.get(AppSetting, SETTING_KEY)
    return datetime.fromisoformat(row.value["refreshed_at"]) if row else None
