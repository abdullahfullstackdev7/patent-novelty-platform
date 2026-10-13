"""Argon2id password hashing and the password policy."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import Settings

MAX_PASSWORD_LENGTH = 128
_COMMON_FILE = Path(__file__).with_name("common_passwords.txt")


class PasswordPolicyError(ValueError):
    """Raised with a message that is safe to show to the user."""


@lru_cache
def _hasher(time_cost: int, memory_kib: int, parallelism: int) -> PasswordHasher:
    return PasswordHasher(
        time_cost=time_cost, memory_cost=memory_kib, parallelism=parallelism, type=Type.ID
    )


def hasher_for(settings: Settings) -> PasswordHasher:
    return _hasher(
        settings.argon2_time_cost, settings.argon2_memory_kib, settings.argon2_parallelism
    )


def hash_password(password: str, settings: Settings) -> str:
    return hasher_for(settings).hash(password)


def verify_password(stored_hash: str | None, password: str, settings: Settings) -> bool:
    """Constant-work check. A missing hash is verified against a dummy so timing matches."""
    hasher = hasher_for(settings)
    target = stored_hash or dummy_hash(settings)
    try:
        ok = hasher.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and stored_hash is not None


@lru_cache
def _dummy(time_cost: int, memory_kib: int, parallelism: int) -> str:
    return _hasher(time_cost, memory_kib, parallelism).hash("not-a-real-password-for-timing")


def dummy_hash(settings: Settings) -> str:
    return _dummy(
        settings.argon2_time_cost, settings.argon2_memory_kib, settings.argon2_parallelism
    )


def needs_rehash(stored_hash: str, settings: Settings) -> bool:
    return hasher_for(settings).check_needs_rehash(stored_hash)


@lru_cache
def common_passwords() -> frozenset[str]:
    lines = _COMMON_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().casefold() for line in lines if line.strip())


def _is_common(password: str) -> bool:
    common = common_passwords()
    folded = password.casefold()
    if folded in common:
        return True
    # "Password1234!" is the common word "password" plus digits and punctuation.
    stripped = re.sub(r"[\d\W_]+$", "", folded)
    return len(stripped) >= 4 and stripped in common


def validate_password(
    password: str,
    settings: Settings,
    *,
    email: str | None = None,
    full_name: str | None = None,
) -> None:
    """Raise PasswordPolicyError unless the password is acceptable."""
    if len(password) < settings.password_min_length:
        raise PasswordPolicyError(
            f"Password must be at least {settings.password_min_length} characters long."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters long."
        )
    if len(set(password)) < 5:
        raise PasswordPolicyError("Password must not be made of a few repeated characters.")
    if _is_common(password):
        raise PasswordPolicyError("This password is too common. Choose a less guessable one.")
    folded = password.casefold()
    if email:
        local = email.split("@", 1)[0].casefold()
        if folded == email.casefold() or (len(local) >= 4 and local in folded):
            raise PasswordPolicyError("Password must not contain your email address.")
    if full_name:
        for part in re.split(r"\s+", full_name.casefold()):
            if len(part) >= 4 and part in folded:
                raise PasswordPolicyError("Password must not contain your name.")
