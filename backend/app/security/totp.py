"""Optional TOTP second factor (RFC 6238) via pyotp."""

from __future__ import annotations

import pyotp

ISSUER = "PriorArt Atlas"


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def verify_code(secret: str, code: str) -> bool:
    """Accept the current 30 second window and one window either side for clock drift."""
    cleaned = code.strip().replace(" ", "")
    if not (cleaned.isdigit() and len(cleaned) == 6):
        return False
    return bool(pyotp.TOTP(secret).verify(cleaned, valid_window=1))
