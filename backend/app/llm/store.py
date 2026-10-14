"""Postgres-backed state for the gateway: settings, call log, response cache and quota."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import AppSetting, LlmCache, LlmCall
from app.llm.types import LLMResult
from app.security.crypto import open_json, seal_json

LLM_SETTINGS_KEY = "llm"
VALID_MODES = ("auto", "groq", "gemini", "local_only")
SETTINGS_TTL_SECONDS = 5.0


@dataclass(frozen=True)
class LlmSettings:
    mode: str
    groq_model: str
    gemini_model: str


class LlmSettingsStore:
    """Global LLM mode and model ids. Environment values are the defaults; admin changes are
    stored in app_settings and win. Reads are cached for a few seconds."""

    def __init__(self, sessions: sessionmaker[Session], settings: Settings, clock=time.monotonic):
        self._sessions = sessions
        self._settings = settings
        self._clock = clock
        self._cached: tuple[float, LlmSettings] | None = None

    def defaults(self) -> LlmSettings:
        s = self._settings
        return LlmSettings(s.llm_mode, s.groq_model, s.gemini_model)

    def get(self) -> LlmSettings:
        now = self._clock()
        if self._cached and now - self._cached[0] < SETTINGS_TTL_SECONDS:
            return self._cached[1]
        defaults = self.defaults()
        with self._sessions() as session:
            row = session.get(AppSetting, LLM_SETTINGS_KEY)
        stored = row.value if row else {}
        current = LlmSettings(
            stored.get("mode", defaults.mode),
            stored.get("groq_model", defaults.groq_model),
            stored.get("gemini_model", defaults.gemini_model),
        )
        self._cached = (now, current)
        return current

    def save(self, new: LlmSettings, user_id: uuid.UUID | None) -> None:
        values = {"mode": new.mode, "groq_model": new.groq_model, "gemini_model": new.gemini_model}
        with self._sessions() as session:
            statement = insert(AppSetting).values(
                key=LLM_SETTINGS_KEY, value=values, updated_by=user_id
            )
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[AppSetting.key],
                    set_={"value": values, "updated_by": user_id, "updated_at": func.now()},
                )
            )
            session.commit()
        self._cached = None


class CallRecorder:
    """Writes one llm_calls row per provider call, cache hit and failed attempt."""

    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    def record(
        self,
        *,
        task: str,
        provider: str,
        model: str,
        case_id: uuid.UUID | None,
        status: str,
        result: LLMResult | None = None,
        cache_hit: bool = False,
        cached_tokens: int = 0,
        latency_ms: int | None = None,
    ) -> None:
        with self._sessions() as session:
            session.add(
                LlmCall(
                    case_id=case_id,
                    task=task,
                    provider=provider,
                    model=model,
                    tokens_in=result.tokens_in if result else 0,
                    tokens_out=result.tokens_out if result else 0,
                    cached_tokens=result.cached_tokens if result else cached_tokens,
                    latency_ms=result.latency_ms if result else latency_ms,
                    status=status,
                    cache_hit=cache_hit,
                )
            )
            session.commit()


class ResponseCache:
    """llm_cache table. The stored response is encrypted: it is derived from the disclosure."""

    def __init__(self, sessions: sessionmaker[Session], settings: Settings):
        self._sessions = sessions
        self._settings = settings

    def get(self, key: str) -> tuple[Any, int, int] | None:
        with self._sessions() as session:
            row = session.get(LlmCache, key)
            if row is None:
                return None
            return open_json(row.response, self._settings)["value"], row.tokens_in, row.tokens_out

    def put(
        self, key: str, task: str, schema_version: str, value: Any, tokens_in: int, tokens_out: int
    ) -> None:
        sealed = seal_json({"value": value}, self._settings)
        with self._sessions() as session:
            statement = insert(LlmCache).values(
                key=key, task=task, schema_version=schema_version, response=sealed,
                tokens_in=tokens_in, tokens_out=tokens_out,
            )  # fmt: skip
            session.execute(statement.on_conflict_do_nothing(index_elements=[LlmCache.key]))
            session.commit()


@dataclass(frozen=True)
class QuotaUsage:
    tokens: int
    requests: int
    tokens_limit: int | None
    requests_limit: int | None

    @property
    def tokens_percent(self) -> float | None:
        return round(100 * self.tokens / self.tokens_limit, 1) if self.tokens_limit else None

    @property
    def requests_percent(self) -> float | None:
        return round(100 * self.requests / self.requests_limit, 1) if self.requests_limit else None


class QuotaTracker:
    """Daily (UTC) token and request usage per provider, read from llm_calls."""

    def __init__(self, sessions: sessionmaker[Session], settings: Settings):
        self._sessions = sessions
        self._settings = settings

    def limits(self, provider: str) -> tuple[int | None, int | None]:
        s = self._settings
        if provider == "groq":
            return s.groq_tpd, s.groq_rpd
        return s.gemini_tpd, s.gemini_rpd

    def usage(self, provider: str, now: datetime | None = None) -> QuotaUsage:
        moment = now or datetime.now(UTC)
        day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        with self._sessions() as session:
            tokens, requests = session.execute(
                select(
                    func.coalesce(func.sum(LlmCall.tokens_in + LlmCall.tokens_out), 0),
                    func.count(),
                ).where(
                    LlmCall.provider == provider,
                    LlmCall.cache_hit.is_(False),
                    LlmCall.status.in_(("ok", "invalid_output")),
                    LlmCall.created_at >= day_start,
                )
            ).one()
        token_limit, request_limit = self.limits(provider)
        return QuotaUsage(int(tokens), int(requests), token_limit, request_limit)

    def allows(self, provider: str, estimated_tokens: int) -> bool:
        usage = self.usage(provider)
        if usage.requests_limit is not None and usage.requests >= usage.requests_limit:
            return False
        return not (
            usage.tokens_limit is not None and usage.tokens + estimated_tokens > usage.tokens_limit
        )
