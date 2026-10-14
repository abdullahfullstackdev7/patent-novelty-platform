"""Authentication: login, rotating refresh cookie, logout, invitations, password and TOTP."""

# No `from __future__ import annotations` here: slowapi wraps the endpoints and FastAPI would
# then fail to resolve the string annotations against the wrapper's globals.
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    PrincipalDep,
    SessionDep,
    SettingsDep,
    ip_of,
    require_same_origin,
)
from app.api.v1.schemas import (
    AcceptInviteRequest,
    ChangePasswordRequest,
    LoginRequest,
    PasswordRequest,
    TokenResponse,
    TotpCodeRequest,
    TotpSetupResponse,
    UserOut,
)
from app.db.models import User
from app.security import passwords, totp
from app.security.crypto import decrypt_text, encrypt_text
from app.security.http import auth_limit, limiter
from app.services import audit
from app.services import auth as auth_service
from app.services.auth import AuthError, Session_

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "refresh_token"
COOKIE_PATH = "/api/v1/auth"


def user_out(user: User, role: str) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role,
        client_id=user.client_id,
        is_active=user.is_active,
        totp_enabled=user.totp_enabled,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _set_cookie(response: Response, token: str, settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def _clear_cookie(response: Response, settings) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _token_response(started: Session_, settings) -> TokenResponse:
    return TokenResponse(
        access_token=started.access.token,
        expires_in=settings.access_token_minutes * 60,
        user=user_out(started.user, started.role),
    )


def _unauthorized(error: AuthError) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        error.message,
        {"WWW-Authenticate": "Bearer", "X-Auth-Error": error.code},
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(auth_limit)
def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    try:
        started = auth_service.login(
            session,
            settings,
            email=body.email,
            password=body.password,
            totp_code=body.totp_code,
            ip=ip_of(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as error:
        raise _unauthorized(error) from None
    session.commit()
    _set_cookie(response, started.refresh_token, settings)
    return _token_response(started, settings)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(require_same_origin)])
@limiter.limit(auth_limit)
def refresh(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse | JSONResponse:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")
    try:
        started = auth_service.rotate_refresh(
            session,
            settings,
            token,
            ip=ip_of(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as error:
        failed = JSONResponse(
            {"detail": error.message},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer", "X-Auth-Error": error.code},
        )
        _clear_cookie(failed, settings)
        return failed
    session.commit()
    _set_cookie(response, started.refresh_token, settings)
    return _token_response(started, settings)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_same_origin)]
)
def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        user_id = auth_service.revoke_presented_token(session, token)
        if user_id is not None:
            audit.record(session, audit.LOGOUT, user_id=user_id, ip=ip_of(request))
        session.commit()
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookie(out, settings)
    return out


@router.get("/me", response_model=UserOut)
def me(principal: PrincipalDep, session: SessionDep) -> UserOut:
    user = session.get(User, principal.id)
    return user_out(user, principal.role)


@router.post("/accept-invite", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(auth_limit)
def accept_invite(
    request: Request, body: AcceptInviteRequest, session: SessionDep, settings: SettingsDep
) -> Response:
    """Set the first password from an invitation, or a new one from an admin reset link."""
    try:
        token_row, user = auth_service.consume_user_token(session, body.token)
    except AuthError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error.message) from None
    if body.full_name and token_row.purpose == "invite":
        user.full_name = body.full_name
    try:
        auth_service.set_password(session, settings, user, body.password)
    except passwords.PasswordPolicyError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from None
    token_row.used_at = datetime.now(UTC)
    audit.record(
        session,
        audit.INVITE_ACCEPTED if token_row.purpose == "invite" else audit.PASSWORD_RESET,
        user_id=user.id,
        ip=ip_of(request),
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(auth_limit)
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    user = session.get(User, principal.id)
    if not passwords.verify_password(user.password_hash, body.current_password, settings):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    try:
        auth_service.set_password(session, settings, user, body.new_password)
    except passwords.PasswordPolicyError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from None
    audit.record(session, audit.PASSWORD_CHANGED, user_id=user.id, ip=ip_of(request))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/totp/setup", response_model=TotpSetupResponse)
def totp_setup(
    principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> TotpSetupResponse:
    """Create a secret. It is stored encrypted and is inactive until /totp/enable succeeds."""
    user = session.get(User, principal.id)
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "TOTP is already enabled")
    secret = totp.new_secret()
    user.totp_secret = encrypt_text(secret, settings)
    session.commit()
    return TotpSetupResponse(
        secret=secret, provisioning_uri=totp.provisioning_uri(secret, user.email)
    )


@router.post("/totp/enable", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(auth_limit)
def totp_enable(
    request: Request,
    body: TotpCodeRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    user = session.get(User, principal.id)
    if user.totp_enabled or not user.totp_secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "Start TOTP setup first")
    if not totp.verify_code(decrypt_text(user.totp_secret, settings), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    user.totp_enabled = True
    audit.record(session, audit.TOTP_ENABLED, user_id=user.id, ip=ip_of(request))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(auth_limit)
def totp_disable(
    request: Request,
    body: PasswordRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    user = session.get(User, principal.id)
    if not passwords.verify_password(user.password_hash, body.password, settings):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is incorrect")
    user.totp_enabled = False
    user.totp_secret = None
    audit.record(session, audit.TOTP_DISABLED, user_id=user.id, ip=ip_of(request))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
