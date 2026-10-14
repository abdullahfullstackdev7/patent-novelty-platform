"""User administration (admin only). Registration is invitation only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import SessionDep, SettingsDep, ip_of, require
from app.api.v1.auth import user_out
from app.api.v1.schemas import (
    InviteRequest,
    InviteResponse,
    ResetResponse,
    UserOut,
    UserUpdate,
)
from app.db.models import Role, User
from app.security.policy import ADMIN, Principal, can_manage_users
from app.services import audit
from app.services import auth as auth_service

router = APIRouter(prefix="/users", tags=["users"])
AdminDep = Depends(require(can_manage_users))


def _role_id(session, name: str) -> int:
    return session.scalars(select(Role.id).where(Role.name == name)).one()


def _role_name(session, user: User) -> str:
    return auth_service.role_name(session, user)


@router.get("", response_model=list[UserOut])
def list_users(
    session: SessionDep, _: Principal = AdminDep, include_demo: bool = False
) -> list[UserOut]:
    """Real users. Seeded demo users are hidden unless include_demo=true."""
    query = select(User, Role.name).join(Role, Role.id == User.role_id).order_by(User.created_at)
    if not include_demo:
        query = query.where(User.is_demo.is_(False))
    rows = session.execute(query).all()
    return [user_out(user, role) for user, role in rows]


@router.post("/invite", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def invite_user(
    request: Request,
    body: InviteRequest,
    session: SessionDep,
    settings: SettingsDep,
    admin: Principal = AdminDep,
) -> InviteResponse:
    """Create the account without a password and return a one-time link token.

    No mail server is assumed: the admin hands the token to the invitee out of band.
    """
    if auth_service.find_user_by_email(session, body.email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    user = User(
        email=body.email.lower(),
        full_name=body.full_name,
        role_id=_role_id(session, body.role),
        client_id=body.client_id,
        password_hash=None,
    )
    session.add(user)
    session.flush()
    token = auth_service.create_user_token(session, settings, user, "invite", admin.id)
    audit.record(
        session,
        audit.USER_INVITED,
        user_id=admin.id,
        ip=ip_of(request),
        entity_type="user",
        entity_id=user.id,
        detail={"role": body.role},
    )
    session.commit()
    expires = datetime.now(UTC) + timedelta(hours=settings.invite_ttl_hours)
    return InviteResponse(user=user_out(user, body.role), invite_token=token, expires_at=expires)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    request: Request,
    body: UserUpdate,
    session: SessionDep,
    admin: Principal = AdminDep,
) -> UserOut:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    previous_role = _role_name(session, user)
    if user.id == admin.id and (
        (body.role is not None and body.role != ADMIN) or body.is_active is False
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Administrators cannot demote or deactivate themselves"
        )
    ip = ip_of(request)
    if body.full_name is not None:
        user.full_name = body.full_name
    if "client_id" in body.model_fields_set:
        user.client_id = body.client_id
    if body.role is not None and body.role != previous_role:
        user.role_id = _role_id(session, body.role)
        audit.record(
            session,
            audit.ROLE_CHANGE,
            user_id=admin.id,
            ip=ip,
            entity_type="user",
            entity_id=user.id,
            detail={"from": previous_role, "to": body.role},
        )
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        if not body.is_active:
            auth_service.revoke_all_for_user(session, user.id)
            audit.record(
                session,
                audit.USER_DEACTIVATED,
                user_id=admin.id,
                ip=ip,
                entity_type="user",
                entity_id=user.id,
            )
    session.commit()
    return user_out(user, _role_name(session, user))


@router.post("/{user_id}/reset-password", response_model=ResetResponse)
def reset_password(
    user_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    admin: Principal = AdminDep,
) -> ResetResponse:
    """Admin reset flow: voids the password and sessions and returns a one-time reset token."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    user.password_hash = None
    user.failed_login_count = 0
    user.locked_until = None
    auth_service.revoke_all_for_user(session, user.id)
    token = auth_service.create_user_token(session, settings, user, "reset", admin.id)
    audit.record(
        session,
        audit.PASSWORD_RESET,
        user_id=admin.id,
        ip=ip_of(request),
        entity_type="user",
        entity_id=user.id,
        detail={"by_admin": True},
    )
    session.commit()
    expires = datetime.now(UTC) + timedelta(hours=settings.invite_ttl_hours)
    return ResetResponse(reset_token=token, expires_at=expires)
