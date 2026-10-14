"""Value objects exchanged between callers, the gateway and providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass
class LLMResult:
    """One provider response."""

    text: str
    json: Any | None
    tokens_in: int
    tokens_out: int
    provider: str
    model: str
    latency_ms: int
    cached_tokens: int = 0
    # Provider rate-limit headers when available (Groq): tokens still allowed this minute.
    remaining_tokens: int | None = None
    reset_seconds: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


class Provider(Protocol):
    """A model provider. `complete` raises the ProviderError subclasses on failure."""

    name: str
    model: str

    def complete(
        self,
        task: str,
        messages: list[Message],
        schema: dict[str, Any] | None,
        max_tokens: int,
    ) -> LLMResult: ...


@dataclass
class GatewayOutput:
    """What callers get back: the validated object plus accounting for every call made."""

    value: Any  # pydantic model instance, or the parsed JSON when no output model was given
    result: LLMResult | None  # the successful provider response, None on a cache hit
    cache_hit: bool
    provider: str | None
    calls: list[LLMResult] = field(default_factory=list)  # includes repair calls

    @property
    def tokens_in(self) -> int:
        return sum(c.tokens_in for c in self.calls)

    @property
    def tokens_out(self) -> int:
        return sum(c.tokens_out for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out
