"""FastAPI dependencies: settings, database session and the authenticated principal."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Role, User
from app.security.http import client_ip
from app.security.policy import Principal
from app.security.tokens import TokenError, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")

UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[Session, Depends(get_session)]


def get_principal(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    """Authenticate the bearer token and load the user. Role and status come from the database
    on every request, so deactivation and role changes take effect immediately."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", UNAUTHORIZED)
    try:
        claims = decode_access_token(credentials.credentials, settings)
        user_id = uuid.UUID(claims["sub"])
    except (TokenError, ValueError, KeyError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", UNAUTHORIZED
        ) from None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", UNAUTHORIZED)
    role = session.get(Role, user.role_id)
    principal = Principal(user.id, user.email, user.full_name, role.name if role else "")
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require(check: Callable[[Principal], bool]) -> Callable[..., Principal]:
    """Dependency factory: 403 unless the policy function allows the principal."""

    def dependency(principal: PrincipalDep) -> Principal:
        if not check(principal):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to do this")
        return principal

    return dependency


def ip_of(request: Request) -> str:
    return client_ip(request)


def require_same_origin(request: Request, settings: SettingsDep) -> None:
    """CSRF defence for the cookie-authenticated endpoints, on top of SameSite=Strict.

    Browsers always send Origin on cross-site requests. When it is present it must be on the
    allow-list. Requests without Origin come from non-browser clients and carry no ambient
    cookie risk.
    """
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in settings.cors_origin_list:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")
