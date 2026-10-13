"""Case lookup with visibility rules: invisible cases look like they do not exist (404)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import Select, exists, or_, select
from sqlalchemy.orm import Session

from app.db.models import Case, CaseShare
from app.security.policy import ADMIN, Principal, can_view_case

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def forbidden() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to do this")


def visible_cases(principal: Principal) -> Select:
    query = select(Case)
    if principal.role == ADMIN:
        return query
    shared = exists().where(CaseShare.case_id == Case.id, CaseShare.user_id == principal.id)
    return query.where(or_(Case.owner_id == principal.id, shared))


def load_case(
    session: Session, principal: Principal, case_id: uuid.UUID
) -> tuple[Case, CaseShare | None]:
    """Return the case and the caller's share, or raise 404 when the caller cannot see it."""
    case = session.get(Case, case_id)
    if case is None:
        raise not_found()
    share = session.get(CaseShare, (case_id, principal.id))
    if not can_view_case(principal, case, share):
        raise not_found()
    return case, share
