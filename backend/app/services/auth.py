"""Login, lockout, rotating refresh tokens, invitations and password resets."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import RefreshToken, Role, User, UserToken
from app.security import passwords, totp
from app.security.crypto import decrypt_text
from app.security.tokens import AccessToken, create_access_token, hash_token, new_opaque_token
from app.services import audit

INVALID_CREDENTIALS = "Invalid credentials"


class AuthError(Exception):
    def __init__(self, message: str, code: str = "invalid_credentials") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class Session_:
    user: User
    role: str
    access: AccessToken
    refresh_token: str


def _now() -> datetime:
    return datetime.now(UTC)


def find_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def role_name(session: Session, user: User) -> str:
    return session.scalars(select(Role.name).where(Role.id == user.role_id)).one()


# ---- refresh tokens -----------------------------------------------------------


def issue_refresh_token(
    session: Session,
    settings: Settings,
    user_id: uuid.UUID,
    *,
    family_id: uuid.UUID | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, RefreshToken]:
    token = new_opaque_token()
    row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        family_id=family_id or uuid.uuid4(),
        token_hash=hash_token(token),
        expires_at=_now() + timedelta(days=settings.refresh_token_days),
        ip_address=ip,
        user_agent=(user_agent or "")[:256] or None,
    )
    session.add(row)
    session.flush()
    return token, row


def revoke_family(session: Session, family_id: uuid.UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def revoke_all_for_user(session: Session, user_id: uuid.UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def _start_session(
    session: Session, settings: Settings, user: User, ip: str | None, user_agent: str | None
) -> Session_:
    role = role_name(session, user)
    access = create_access_token(user.id, role, settings)
    refresh, _ = issue_refresh_token(session, settings, user.id, ip=ip, user_agent=user_agent)
    return Session_(user, role, access, refresh)


def rotate_refresh(
    session: Session,
    settings: Settings,
    token: str,
    *,
    ip: str | None,
    user_agent: str | None,
) -> Session_:
    """Exchange a refresh token for a new pair. Reusing a rotated token revokes the family."""
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)))
    if row is None:
        raise AuthError("Invalid refresh token", "invalid_refresh")
    if row.revoked_at is not None or row.replaced_by is not None:
        revoke_family(session, row.family_id)
        audit.record(
            session,
            audit.REFRESH_REUSE,
            user_id=row.user_id,
            ip=ip,
            entity_type="refresh_family",
            entity_id=row.family_id,
        )
        session.commit()
        raise AuthError("Invalid refresh token", "invalid_refresh")
    if row.expires_at <= _now():
        raise AuthError("Refresh token expired", "invalid_refresh")
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        revoke_family(session, row.family_id)
        session.commit()
        raise AuthError("Invalid refresh token", "invalid_refresh")

    role = role_name(session, user)
    new_token, new_row = issue_refresh_token(
        session, settings, user.id, family_id=row.family_id, ip=ip, user_agent=user_agent
    )
    row.revoked_at = _now()
    row.replaced_by = new_row.id
    return Session_(user, role, create_access_token(user.id, role, settings), new_token)


def revoke_presented_token(session: Session, token: str) -> uuid.UUID | None:
    """Logout: revoke the whole family of the presented token. Returns the user id if known."""
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)))
    if row is None:
        return None
    revoke_family(session, row.family_id)
    return row.user_id


# ---- login --------------------------------------------------------------------


def _register_failure(user: User, settings: Settings) -> None:
    user.failed_login_count += 1
    over = user.failed_login_count - settings.lockout_threshold
    if over >= 0:
        minutes = min(2**over, settings.lockout_max_minutes)  # 1, 2, 4, 8 ... minutes
        user.locked_until = _now() + timedelta(minutes=minutes)


def login(
    session: Session,
    settings: Settings,
    *,
    email: str,
    password: str,
    totp_code: str | None,
    ip: str | None,
    user_agent: str | None,
) -> Session_:
    user = find_user_by_email(session, email)
    now = _now()
    locked = bool(user and user.locked_until and user.locked_until > now)
    # Always run the hash comparison so unknown accounts take as long as known ones.
    valid = passwords.verify_password(user.password_hash if user else None, password, settings)

    def fail(reason: str, count: bool) -> AuthError:
        if user is not None and count:
            _register_failure(user, settings)
        audit.record(
            session,
            audit.LOGIN_FAILED,
            user_id=user.id if user else None,
            ip=ip,
            detail={"reason": reason, "known_account": user is not None},
        )
        session.commit()
        return AuthError(INVALID_CREDENTIALS)

    if user is None or not user.is_active or user.password_hash is None:
        raise fail("unknown_or_inactive", count=False)
    if locked:
        raise fail("locked", count=False)
    if not valid:
        raise fail("bad_password", count=True)

    if user.totp_enabled:
        if not totp_code:
            raise AuthError("A TOTP code is required", "totp_required")
        secret = decrypt_text(user.totp_secret or "", settings)
        if not totp.verify_code(secret, totp_code):
            raise fail("bad_totp", count=True)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if passwords.needs_rehash(user.password_hash, settings):
        user.password_hash = passwords.hash_password(password, settings)
    started = _start_session(session, settings, user, ip, user_agent)
    audit.record(session, audit.LOGIN_SUCCESS, user_id=user.id, ip=ip)
    return started


# ---- invitations and resets ---------------------------------------------------


def create_user_token(
    session: Session,
    settings: Settings,
    user: User,
    purpose: str,
    created_by: uuid.UUID | None,
) -> str:
    """One-time token, valid for INVITE_TTL_HOURS. Older unused tokens for the user are voided."""
    session.execute(
        update(UserToken)
        .where(UserToken.user_id == user.id, UserToken.used_at.is_(None))
        .values(used_at=_now())
    )
    token = new_opaque_token()
    session.add(
        UserToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(token),
            expires_at=_now() + timedelta(hours=settings.invite_ttl_hours),
            created_by=created_by,
        )
    )
    return token


def consume_user_token(session: Session, token: str) -> tuple[UserToken, User]:
    row = session.scalar(select(UserToken).where(UserToken.token_hash == hash_token(token)))
    if row is None or row.used_at is not None or row.expires_at <= _now():
        raise AuthError("This link is invalid or has expired", "invalid_token")
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthError("This link is invalid or has expired", "invalid_token")
    return row, user


def set_password(session: Session, settings: Settings, user: User, new_password: str) -> None:
    """Validate and store a new password, and sign the user out everywhere."""
    passwords.validate_password(new_password, settings, email=user.email, full_name=user.full_name)
    user.password_hash = passwords.hash_password(new_password, settings)
    user.failed_login_count = 0
    user.locked_until = None
    revoke_all_for_user(session, user.id)
