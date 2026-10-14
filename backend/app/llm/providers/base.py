"""Helpers shared by provider implementations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_DURATION = re.compile(
    r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?"
)
_RETRY_IN_TEXT = re.compile(r"(?i)retry(?:Delay)?[^0-9]{0,30}(\d+(?:\.\d+)?)\s*s")


def parse_duration(value: str | None) -> float | None:
    """'7.66s', '2m59.56s', '120ms' or a plain number of seconds -> seconds."""
    if not value:
        return None
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    match = _DURATION.fullmatch(text)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds, millis = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def retry_after_from_headers(headers: Mapping[str, str] | None) -> float | None:
    if not headers:
        return None
    lowered = {k.lower(): v for k, v in headers.items()}
    return parse_duration(lowered.get("retry-after"))


def retry_after_from_text(message: str) -> float | None:
    match = _RETRY_IN_TEXT.search(message)
    return float(match.group(1)) if match else None


def int_header(headers: Mapping[str, str] | None, name: str) -> int | None:
    if not headers:
        return None
    for key, value in headers.items():
        if key.lower() == name:
            try:
                return int(float(value))
            except ValueError:
                return None
    return None


def parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def schema_name(task: str) -> str:
    """Provider schema names allow letters, digits, underscore and hyphen."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", task)[:60] or "output"
