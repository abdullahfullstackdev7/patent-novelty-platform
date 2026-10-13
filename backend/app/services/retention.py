"""Per-case data retention: purge cases older than their retention period."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Case
from app.services import audit


def purge_expired(
    session: Session, *, now: datetime | None = None, actor_id=None, ip: str | None = None
) -> list[str]:
    """Hard-delete cases whose created_at + retention_days is in the past.

    Cascades remove the disclosure, search runs, chart, reports, shares and jobs. Returns the
    ids of the deleted cases. The audit entry carries ids only, never case content.
    """
    moment = now or datetime.now(UTC)
    expired = session.scalars(
        select(Case.id).where(
            Case.retention_days.is_not(None),
            Case.created_at + func.make_interval(0, 0, 0, Case.retention_days) < moment,
        )
    ).all()
    if expired:
        session.execute(delete(Case).where(Case.id.in_(expired)))
    audit.record(
        session,
        audit.RETENTION_PURGE,
        user_id=actor_id,
        ip=ip,
        detail={"count": len(expired), "case_ids": [str(i) for i in expired][:100]},
    )
    return [str(i) for i in expired]
