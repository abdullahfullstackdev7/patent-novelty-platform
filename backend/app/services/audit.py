"""Audit log writer. Never stores secrets or disclosure text."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog

# Audit actions (login, case view, export, approval, role change, and the rest of the trail)
LOGIN_SUCCESS = "login_success"
LOGIN_FAILED = "login_failed"
LOGOUT = "logout"
REFRESH_REUSE = "refresh_reuse_detected"
PASSWORD_CHANGED = "password_changed"
PASSWORD_RESET = "password_reset"
TOTP_ENABLED = "totp_enabled"
TOTP_DISABLED = "totp_disabled"
USER_INVITED = "user_invited"
INVITE_ACCEPTED = "invite_accepted"
ROLE_CHANGE = "role_change"
USER_DEACTIVATED = "user_deactivated"
CASE_CREATE = "case_create"
CASE_VIEW = "case_view"
CASE_DELETE = "case_delete"
CASE_SHARE = "case_share"
CASE_UNSHARE = "case_unshare"
CASE_RUN = "case_run"
REPORT_GENERATE = "report_generate"
REPORT_EDIT = "report_edit"
EXPORT = "export"
REVIEW_SUBMIT = "review_submit"
APPROVE = "approve"
REQUEST_CHANGES = "request_changes"
CELL_OVERRIDE = "cell_override"
RETENTION_PURGE = "retention_purge"

_SENSITIVE = ("password", "token", "secret", "text", "problem", "solution", "content", "field")
MAX_DETAIL_VALUE = 200


def _clean(detail: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (detail or {}).items():
        if any(marker in key.lower() for marker in _SENSITIVE):
            cleaned[key] = "[redacted]"
        elif isinstance(value, str) and len(value) > MAX_DETAIL_VALUE:
            cleaned[key] = value[:MAX_DETAIL_VALUE] + "..."
        elif isinstance(value, uuid.UUID):
            cleaned[key] = str(value)
        else:
            cleaned[key] = value
    return cleaned


def record(
    session: Session,
    action: str,
    *,
    user_id: uuid.UUID | None,
    ip: str | None,
    entity_type: str | None = None,
    entity_id: Any = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the session. The caller commits it with its own change."""
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            ip_address=ip,
            detail=_clean(detail),
        )
    )
