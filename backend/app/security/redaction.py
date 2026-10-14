"""Scrub secrets and disclosure text from log output."""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "[REDACTED]"

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_FERNET = re.compile(r"gAAAA[A-Za-z0-9_\-=]{20,}")
_API_KEY = re.compile(
    r"(?<![A-Za-z0-9])(?:gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9_-]{20,})"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE = re.compile(
    r"""(?ix)
    (?P<key>"?(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|set-cookie
        |refresh_token|access_token|totp_code|totp_secret|jwt_secret|fernet_key
        |problem|solution|technical_field|disclosure|ciphertext)"?)
    (?P<sep>\s*[:=]\s*)
    (?P<quote>["']?)
    (?P<value>[^\s,"';}&]+)
    """
)


def redact(text: str) -> str:
    text = _JWT.sub(REDACTED, text)
    text = _FERNET.sub(REDACTED, text)
    text = _API_KEY.sub(REDACTED, text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    return _KEY_VALUE.sub(lambda m: f"{m['key']}{m['sep']}{m['quote']}{REDACTED}", text)


class RedactingFilter(logging.Filter):
    """Filter form of redact() for handlers that prefer filters."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Format first so secrets passed as arguments are seen, then drop the arguments.
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        return True


_installed = False


def install_log_redaction() -> None:
    """Redact every log record at creation time, whichever logger or handler emits it."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()
    scrub = RedactingFilter()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        scrub.filter(record)
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
