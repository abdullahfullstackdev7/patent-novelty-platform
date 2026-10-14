"""Exception types shared by providers and the gateway."""

from __future__ import annotations


class LLMError(Exception):
    """Base class."""


class ProviderError(LLMError):
    """A provider call failed. `retryable` errors are retried on the same provider first."""

    retryable = True
    counts_against_breaker = True

    def __init__(self, message: str, *, provider: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.provider = provider
        self.retry_after = retry_after


class ProviderRateLimited(ProviderError):
    """HTTP 429. `retry_after` is seconds when the provider said how long to wait."""


class ProviderUnavailable(ProviderError):
    """HTTP 5xx or a connection failure."""


class ProviderTimeout(ProviderError):
    """The request exceeded the configured timeout."""


class ProviderRejected(ProviderError):
    """HTTP 4xx other than 429: the request itself was refused. Not retried on the same
    provider and not counted against the circuit breaker, but another provider may accept it."""

    retryable = False
    counts_against_breaker = False


class OutputTruncated(ProviderError):
    """The model hit max tokens, so the JSON is incomplete."""

    retryable = False
    counts_against_breaker = False


class InvalidOutput(LLMError):
    """The model answered but the output does not satisfy the schema, even after one repair."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


class LocalOnly(LLMError):
    """The effective mode is local_only: no LLM call is made. Callers use the template path."""


class AllProvidersUnavailable(LLMError):
    """Every allowed provider failed or is blocked. Callers use the deterministic template and
    label the result 'machine summary, no LLM'."""

    def __init__(self, message: str, attempts: list[str] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


class PromptTooLarge(LLMError):
    """The request cannot fit the per-request token budget of the only allowed provider."""
