"""Scripted fake providers, a fake clock and a gateway builder for the LLM tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.config import Settings
from app.llm.gateway import LLMGateway
from app.llm.store import CallRecorder, LlmSettingsStore, QuotaTracker, ResponseCache
from app.llm.types import LLMResult, Message

ELEMENTS_OK = {"elements": [{"id": "E1", "text": "alpha"}, {"id": "E2", "text": "beta"}]}
CELLS_OK = {"cells": [{"e": "E1", "s": "d", "p": "P1", "r": "matches the claim"}]}


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Reply:
    """One scripted successful answer."""

    data: Any = None
    tokens_in: int = 300
    tokens_out: int = 60
    cached: int = 0
    remaining: int | None = None
    reset: float | None = None
    raw_text: str | None = None  # use to simulate output that is not JSON


@dataclass
class Call:
    task: str
    messages: list[Message]
    schema: dict[str, Any] | None
    max_tokens: int

    @property
    def user(self) -> str:
        return next(m.content for m in self.messages if m.role == "user")


@dataclass
class FakeProvider:
    name: str
    script: list[Any] = field(default_factory=list)  # Reply | dict | Exception
    model: str = "fake-model"
    default: Any = field(default_factory=lambda: Reply(ELEMENTS_OK))
    calls: list[Call] = field(default_factory=list)

    def complete(
        self, task: str, messages: list[Message], schema: dict[str, Any] | None, max_tokens: int
    ) -> LLMResult:
        self.calls.append(Call(task, messages, schema, max_tokens))
        item = self.script.pop(0) if self.script else self.default
        if isinstance(item, BaseException):
            raise item
        reply = item if isinstance(item, Reply) else Reply(item)
        body = reply.raw_text if reply.raw_text is not None else json.dumps(reply.data)
        parsed = None if reply.raw_text is not None else reply.data
        return LLMResult(
            text=body, json=parsed, tokens_in=reply.tokens_in, tokens_out=reply.tokens_out,
            provider=self.name, model=self.model, latency_ms=7, cached_tokens=reply.cached,
            remaining_tokens=reply.remaining, reset_seconds=reply.reset,
        )  # fmt: skip


def make_gateway(
    session_factory, settings: Settings, providers: dict[str, FakeProvider], **overrides
) -> tuple[LLMGateway, list[float], Clock]:
    """Gateway on real tables with a fake clock. rng=0.5 makes backoff jitter exactly 1.0, so
    waits are deterministic: 0.5 s, 1 s, 2 s ... and retry-after hints get +0.1 s."""
    tuned = settings.model_copy(update={"llm_retry_attempts": 2, "llm_mode": "auto", **overrides})
    clock = Clock()
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    gateway = LLMGateway(
        providers,
        tuned,
        LlmSettingsStore(session_factory, tuned, clock),
        ResponseCache(session_factory, tuned),
        CallRecorder(session_factory),
        QuotaTracker(session_factory, tuned),
        clock=clock,
        sleep=sleep,
        rng=lambda: 0.5,
    )
    return gateway, sleeps, clock


def call_rows(session_factory) -> list[tuple]:
    """(provider, task, status, tokens_in, tokens_out, cache_hit) in insertion order."""
    with session_factory() as session:
        rows = session.execute(
            text(
                "SELECT provider, task, status, tokens_in, tokens_out, cache_hit "
                "FROM llm_calls ORDER BY id"
            )
        )
        return [tuple(r) for r in rows]


def count(session_factory, table: str) -> int:
    with session_factory() as session:
        return session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
