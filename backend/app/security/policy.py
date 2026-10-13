"""Authorization policy: one function per permission.

Roles: admin, attorney, analyst, viewer. Case access is role plus ownership plus sharing.
Functions only decide; the API layer maps "cannot see" to 404 and "cannot do" to 403.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

ADMIN = "admin"
ATTORNEY = "attorney"
ANALYST = "analyst"
VIEWER = "viewer"
ROLES = (ADMIN, ATTORNEY, ANALYST, VIEWER)

CASE_CREATORS = frozenset({ADMIN, ATTORNEY, ANALYST})
CASE_WORKERS = frozenset({ATTORNEY, ANALYST})  # may own and edit cases


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. `role` always comes from the database, never from the token."""

    id: uuid.UUID
    email: str
    full_name: str
    role: str


class CaseLike(Protocol):
    owner_id: uuid.UUID


class ShareLike(Protocol):
    permission: str


# ---- platform ----------------------------------------------------------------


def can_manage_users(user: Principal) -> bool:
    return user.role == ADMIN


def can_view_analytics(user: Principal) -> bool:
    return user.role == ADMIN


def can_view_billing(user: Principal) -> bool:
    return user.role == ADMIN


def can_view_audit_log(user: Principal) -> bool:
    return user.role == ADMIN


def can_run_retention_purge(user: Principal) -> bool:
    return user.role == ADMIN


# ---- cases -------------------------------------------------------------------


def can_create_case(user: Principal) -> bool:
    return user.role in CASE_CREATORS


def can_parse_upload(user: Principal) -> bool:
    return user.role in CASE_CREATORS


def can_view_case(user: Principal, case: CaseLike, share: ShareLike | None) -> bool:
    """Visibility. Callers answer 404 when this is false."""
    return user.role == ADMIN or case.owner_id == user.id or share is not None


def can_edit_case(user: Principal, case: CaseLike, share: ShareLike | None) -> bool:
    """Edit the case, its disclosure and report, run searches, submit for review."""
    if not can_view_case(user, case, share):
        return False
    if user.role == ADMIN:
        return True
    if user.role not in CASE_WORKERS:
        return False
    return case.owner_id == user.id or (share is not None and share.permission == "write")


def can_run_case(user: Principal, case: CaseLike, share: ShareLike | None) -> bool:
    return can_edit_case(user, case, share)


def can_delete_case(user: Principal, case: CaseLike) -> bool:
    return user.role == ADMIN or (user.role in CASE_WORKERS and case.owner_id == user.id)


def can_share_case(user: Principal, case: CaseLike) -> bool:
    return can_delete_case(user, case)


def can_export_case(user: Principal, case: CaseLike, share: ShareLike | None) -> bool:
    return can_view_case(user, case, share)


# ---- review ------------------------------------------------------------------


def can_submit_for_review(user: Principal, case: CaseLike, share: ShareLike | None) -> bool:
    return can_edit_case(user, case, share)


def can_review_case(user: Principal, case: CaseLike, share: ShareLike | None) -> bool:
    """Approve, request changes and override chart cells: attorneys who can see the case.

    Administrators can see every case but do not give legal sign-off.
    """
    return user.role == ATTORNEY and can_view_case(user, case, share)
