"""Admin-only endpoints (analytics summary, billing plans, audit log, retention) and health."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, text

from app.api.deps import SessionDep, ip_of, require
from app.api.v1.schemas import AuditOut, PlanOut
from app.db.models import AuditLog, Case, Plan, Report, Role, User
from app.security import policy
from app.services import retention

router = APIRouter()
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])
billing_router = APIRouter(prefix="/billing", tags=["billing"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])
health_router = APIRouter(prefix="/health", tags=["health"])


@analytics_router.get("/summary")
def analytics_summary(
    session: SessionDep, _: policy.Principal = Depends(require(policy.can_view_analytics))
) -> dict:
    """Headline counts. Revenue, usage and LLM analytics arrive with the Phase 6 data layer."""
    by_status = dict(session.execute(select(Case.status, func.count()).group_by(Case.status)).all())
    by_role = dict(
        session.execute(
            select(Role.name, func.count(User.id))
            .join(User, User.role_id == Role.id, isouter=True)
            .group_by(Role.name)
        ).all()
    )
    approved = session.scalar(
        select(func.count()).select_from(Report).where(Report.state == "approved")
    )
    return {"cases_by_status": by_status, "users_by_role": by_role, "reports_approved": approved}


@billing_router.get("/plans", response_model=list[PlanOut])
def list_plans(
    session: SessionDep, _: policy.Principal = Depends(require(policy.can_view_billing))
) -> list[PlanOut]:
    plans = session.scalars(select(Plan).order_by(Plan.monthly_price)).all()
    return [
        PlanOut(
            id=p.id, code=p.code, name=p.name, monthly_price=float(p.monthly_price),
            included_reports=p.included_reports, overage_price=float(p.overage_price),
            seats=p.seats,
        )
        for p in plans
    ]  # fmt: skip


@admin_router.get("/audit", response_model=list[AuditOut])
def audit_log(
    session: SessionDep,
    _: policy.Principal = Depends(require(policy.can_view_audit_log)),
    action: str | None = Query(default=None, max_length=64),
    user_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AuditOut]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    if action:
        query = query.where(AuditLog.action == action)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    return [
        AuditOut(
            id=r.id, user_id=r.user_id, action=r.action, entity_type=r.entity_type,
            entity_id=r.entity_id, ip_address=r.ip_address, detail=r.detail,
            created_at=r.created_at,
        )
        for r in session.scalars(query)
    ]  # fmt: skip


@admin_router.post("/retention/purge")
def purge_retention(
    request: Request,
    session: SessionDep,
    admin: policy.Principal = Depends(require(policy.can_run_retention_purge)),
) -> dict:
    deleted = retention.purge_expired(session, actor_id=admin.id, ip=ip_of(request))
    session.commit()
    return {"deleted": len(deleted), "case_ids": deleted}


@health_router.get("")
def health() -> dict:
    return {"status": "ok"}


@health_router.get("/ready")
def ready(session: SessionDep) -> dict:
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from None
    return {"status": "ready"}
