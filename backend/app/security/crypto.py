"""Application-level encryption with Fernet and key rotation through MultiFernet."""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import Settings, get_settings


class DecryptionError(Exception):
    """Ciphertext is corrupt or was written with a key that is no longer configured."""


def _multi(settings: Settings) -> MultiFernet:
    return MultiFernet([Fernet(key) for key in settings.fernet_keys])


def encrypt_text(value: str, settings: Settings | None = None) -> str:
    """Encrypt with the primary key. Returns a URL-safe token string."""
    return _multi(settings or get_settings()).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(token: str, settings: Settings | None = None) -> str:
    try:
        return _multi(settings or get_settings()).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as error:
        raise DecryptionError("cannot decrypt value") from error


def rotate_token(token: str, settings: Settings | None = None) -> str:
    """Re-encrypt a token with the primary key (old keys can then be retired)."""
    try:
        return _multi(settings or get_settings()).rotate(token.encode("ascii")).decode("ascii")
    except InvalidToken as error:
        raise DecryptionError("cannot rotate value") from error


def seal_json(value: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """Encrypt a JSON document so it can live in a JSONB column."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"v": 1, "ciphertext": encrypt_text(payload, settings)}


def open_json(sealed: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    if sealed.get("v") != 1 or "ciphertext" not in sealed:
        raise DecryptionError("unsupported sealed document")
    return json.loads(decrypt_text(sealed["ciphertext"], settings))
