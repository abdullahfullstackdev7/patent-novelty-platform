"""Access tokens (short-lived JWT) and opaque refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.config import Settings

ALGORITHM = "HS256"
ACCESS_TYPE = "access"
ISSUER = "priorart-atlas"


class TokenError(Exception):
    """The presented token is missing, malformed, expired or not an access token."""


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_at: datetime


def create_access_token(user_id: uuid.UUID, role: str, settings: Settings) -> AccessToken:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    claims = {
        "iss": ISSUER,
        "sub": str(user_id),
        "role": role,  # informational only, the database decides the effective role
        "typ": ACCESS_TYPE,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": expires,
    }
    return AccessToken(jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM), expires)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verify signature, expiry, issuer and type. Only HS256 is accepted (no `none`)."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "jti", "typ", "iss"]},
        )
    except jwt.PyJWTError as error:
        raise TokenError(str(error)) from error
    if claims.get("typ") != ACCESS_TYPE:
        raise TokenError("wrong token type")
    return claims


def new_opaque_token() -> str:
    """URL-safe random token with 384 bits of entropy."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
