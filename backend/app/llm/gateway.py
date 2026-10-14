"""LLM gateway: Groq first, Gemini as fallback, with a cache, token budgets and accounting.

Order of checks for every call (section 3 of the plan):
  1. effective mode (global setting and per-case mode, the more restrictive wins),
  2. response cache (identical request costs nothing),
  3. per provider: request size, circuit breaker, daily quota, per-minute token bucket,
  4. the call with bounded retries and jittered backoff that honours retry-after,
  5. schema validation with at most one targeted repair call,
  6. accounting in llm_calls and storage in the cache.
If no provider can answer the gateway raises AllProvidersUnavailable and the caller falls back
to the deterministic template labelled 'machine summary, no LLM'.
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
)

from app.config import Settings
from app.llm.budget import CircuitBreaker, TokenBucket, estimate_tokens
from app.llm.errors import (
    AllProvidersUnavailable,
    InvalidOutput,
    LocalOnly,
    PromptTooLarge,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
)
from app.llm.prompts import PromptSpec
from app.llm.providers.base import parse_json
from app.llm.schema import cache_key, provider_schema, set_value_at, subschema, value_at
from app.llm.store import CallRecorder, LlmSettingsStore, QuotaTracker, ResponseCache
from app.llm.types import GatewayOutput, LLMResult, Message, Provider

logger = logging.getLogger("priorart.llm")

PROVIDER_ORDER = {"auto": ("groq", "gemini"), "groq": ("groq",), "gemini": ("gemini",)}
REPAIR_SYSTEM = (
    "Fix one JSON value so that it satisfies the given schema. "
    'Reply with JSON of the form {"value": <fixed value>} and nothing else.'
)
REPAIR_MAX_TOKENS = 500
RAW_SNIPPET_CHARS = 800
JITTER = 0.25
BACKOFF_START = 0.5


def resolve_mode(case_mode: str | None, global_mode: str) -> str:
    """The more restrictive setting wins: local_only anywhere means no LLM call at all.
    Otherwise a specific case mode overrides the global one, and 'auto' defers to it."""
    if "local_only" in (case_mode, global_mode):
        return "local_only"
    if case_mode and case_mode != "auto":
        return case_mode
    return global_mode


@dataclass
class _Skip:
    provider: str
    reason: str


class LLMGateway:
    def __init__(
        self,
        providers: Mapping[str, Provider],
        settings: Settings,
        store: LlmSettingsStore,
        cache: ResponseCache,
        recorder: CallRecorder,
        quota: QuotaTracker,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.providers = dict(providers)
        self.settings = settings
        self.store = store
        self.cache = cache
        self.recorder = recorder
        self.quota = quota
        self._sleep = sleep
        self._rng = rng
        self.buckets = {
            "groq": TokenBucket(settings.groq_tpm, settings.groq_rpm, clock),
            "gemini": TokenBucket(settings.gemini_tpm, settings.gemini_rpm, clock),
        }
        self.breakers = {
            name: CircuitBreaker(
                settings.llm_breaker_failures, settings.llm_breaker_open_seconds, clock
            )
            for name in ("groq", "gemini")
        }

    # ------------------------------------------------------------------ public API

    def effective_mode(self, case_mode: str | None = "auto") -> str:
        return resolve_mode(case_mode, self.store.get().mode)

    def run(
        self,
        spec: PromptSpec,
        user: str,
        *,
        case_id: uuid.UUID | None = None,
        case_mode: str | None = "auto",
    ) -> GatewayOutput:
        """Run one task. Returns the validated output model plus token accounting."""
        current = self.store.get()
        mode = resolve_mode(case_mode, current.mode)
        if mode == "local_only":
            raise LocalOnly("LLM calls are disabled for this case")

        messages = spec.messages(user)
        key = cache_key(spec.task, spec.schema_version, messages)
        hit = self._cache_lookup(spec, key)
        if hit is not None:
            self.recorder.record(
                task=spec.task, provider="cache", model="cache", case_id=case_id,
                status="ok", cache_hit=True,
            )  # fmt: skip
            return GatewayOutput(value=hit, result=None, cache_hit=True, provider=None)

        schema = provider_schema(spec.output_model)
        models = {"groq": current.groq_model, "gemini": current.gemini_model}
        calls: list[LLMResult] = []
        result = self._complete(
            spec.task, messages, schema, spec.max_tokens, mode, models, case_id, calls
        )
        value, valid = self._validate(spec, result, schema, mode, models, case_id, calls)
        self.recorder.record(
            task=spec.task, provider=result.provider, model=result.model, case_id=case_id,
            status="ok" if valid else "invalid_output", result=result,
        )  # fmt: skip
        self.cache.put(
            key, spec.task, spec.schema_version, value.model_dump(),
            sum(c.tokens_in for c in calls), sum(c.tokens_out for c in calls),
        )  # fmt: skip
        return GatewayOutput(
            value=value, result=result, cache_hit=False, provider=result.provider, calls=calls
        )

    # ------------------------------------------------------------------ cache

    def _cache_lookup(self, spec: PromptSpec, key: str) -> BaseModel | None:
        try:
            found = self.cache.get(key)
            if found is None:
                return None
            return spec.output_model.model_validate(found[0])
        except Exception:  # an unreadable or outdated entry is just a miss
            logger.warning("llm cache entry for %s could not be used", spec.task)
            return None

    # ------------------------------------------------------------------ provider selection

    def _complete(
        self,
        task: str,
        messages: list[Message],
        schema: dict[str, Any] | None,
        max_tokens: int,
        mode: str,
        models: Mapping[str, str],
        case_id: uuid.UUID | None,
        calls: list[LLMResult],
    ) -> LLMResult:
        estimate = sum(estimate_tokens(m.content) for m in messages) + max_tokens
        candidates = [name for name in PROVIDER_ORDER[mode] if name in self.providers]
        if not candidates:
            raise AllProvidersUnavailable(f"no provider is configured for mode {mode}")
        skips: list[_Skip] = []

        for position, name in enumerate(candidates):
            provider = self.providers[name]
            provider.model = models[name]
            breaker, bucket = self.breakers[name], self.buckets[name]
            is_last = position == len(candidates) - 1

            if name == "groq" and estimate > self.settings.llm_max_request_tokens:
                limit = self.settings.llm_max_request_tokens
                skips.append(
                    _Skip(
                        name, f"request of about {estimate} tokens is over the {limit} token budget"
                    )
                )
                continue
            if breaker.snapshot().state == "open":
                skips.append(_Skip(name, "circuit breaker is open"))
                continue
            if not self.quota.allows(name, estimate):
                skips.append(_Skip(name, "daily quota exhausted"))
                continue
            wait = bucket.wait_needed(estimate)
            if wait > 0:
                if not is_last or wait > self.settings.llm_max_bucket_wait_seconds:
                    skips.append(_Skip(name, f"per-minute budget full (wait {wait:.0f}s)"))
                    continue
                self._sleep(wait)
            if not breaker.allow():  # last check: may claim the half-open trial slot
                skips.append(_Skip(name, "circuit breaker is open"))
                continue

            try:
                result = self._call_with_retries(
                    provider, task, messages, schema, max_tokens, case_id
                )
            except ProviderError as error:
                if error.counts_against_breaker:
                    breaker.record_failure()
                else:
                    breaker.release()
                skips.append(_Skip(name, f"{type(error).__name__}: {error}"))
                logger.warning(
                    "llm provider %s failed for %s: %s", name, task, type(error).__name__
                )
                continue

            breaker.record_success()
            bucket.update_from_headers(result.remaining_tokens, result.reset_seconds)
            bucket.record(max(result.total_tokens - result.cached_tokens, 0))
            calls.append(result)
            return result

        reasons = [f"{s.provider}: {s.reason}" for s in skips]
        if (
            skips
            and all("token budget" in s.reason for s in skips)
            and len(skips) == len(candidates)
        ):
            raise PromptTooLarge("; ".join(reasons))
        raise AllProvidersUnavailable("; ".join(reasons), reasons)

    # ------------------------------------------------------------------ one provider, with retries

    def _call_with_retries(
        self,
        provider: Provider,
        task: str,
        messages: list[Message],
        schema: dict[str, Any] | None,
        max_tokens: int,
        case_id: uuid.UUID | None,
    ) -> LLMResult:
        max_wait = self.settings.llm_retry_max_wait_seconds

        def worth_retrying(error: BaseException) -> bool:
            if not isinstance(error, ProviderError) or not error.retryable:
                return False
            # A long retry-after means this provider is busy: fail over instead of waiting.
            return error.retry_after is None or error.retry_after <= max_wait

        def backoff(state: RetryCallState) -> float:
            error = state.outcome.exception() if state.outcome else None
            hinted = getattr(error, "retry_after", None)
            if hinted is not None:
                return min(hinted, max_wait) + self._rng() * 0.2
            base = min(BACKOFF_START * 2 ** (state.attempt_number - 1), max_wait)
            return base * (1 - JITTER + 2 * JITTER * self._rng())

        def attempt() -> LLMResult:
            started = time.perf_counter()
            try:
                return provider.complete(task, messages, schema, max_tokens)
            except ProviderError as error:
                self.recorder.record(
                    task=task, provider=provider.name, model=provider.model, case_id=case_id,
                    status=_status_for(error),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )  # fmt: skip
                raise

        retrying = Retrying(
            retry=retry_if_exception(worth_retrying),
            stop=stop_after_attempt(max(self.settings.llm_retry_attempts, 1)),
            wait=backoff,
            sleep=self._sleep,
            reraise=True,
        )
        return retrying(attempt)

    # ------------------------------------------------------------------ validation and repair

    def _validate(
        self,
        spec: PromptSpec,
        result: LLMResult,
        schema: dict[str, Any],
        mode: str,
        models: Mapping[str, str],
        case_id: uuid.UUID | None,
        calls: list[LLMResult],
    ) -> tuple[BaseModel, bool]:
        """Validate with Pydantic. On failure make at most one repair call that carries only the
        invalid field. Returns (value, first_try_was_valid)."""
        data = result.json if result.json is not None else parse_json(result.text)
        error = self._first_error(spec.output_model, data)
        if error is None:
            return spec.output_model.model_validate(data), True

        loc, message = error
        current = (
            result.text[:RAW_SNIPPET_CHARS] if data is None or not loc else _safe_value(data, loc)
        )
        fragment = schema if not loc else subschema(schema, loc)
        repair_schema = {
            "type": "object",
            "properties": {"value": fragment},
            "required": ["value"],
            "additionalProperties": False,
        }
        repair_messages = [
            Message("system", REPAIR_SYSTEM),
            Message(
                "user",
                f"Error: {message}\nCurrent value: {json.dumps(current, ensure_ascii=False)}",
            ),
        ]
        try:
            fix = self._complete(
                f"{spec.task}.repair", repair_messages, repair_schema,
                min(spec.max_tokens, REPAIR_MAX_TOKENS), mode, models, case_id, calls,
            )  # fmt: skip
        except (ProviderError, AllProvidersUnavailable, PromptTooLarge) as failure:
            raise InvalidOutput(
                f"{spec.task}: invalid output and repair unavailable", result.text
            ) from failure
        self.recorder.record(
            task=f"{spec.task}.repair", provider=fix.provider, model=fix.model, case_id=case_id,
            status="ok", result=fix,
        )  # fmt: skip

        fixed = fix.json.get("value") if isinstance(fix.json, dict) else None
        if fixed is None:
            raise InvalidOutput(f"{spec.task}: repair returned no value", fix.text)
        if loc and isinstance(data, (dict, list)):
            try:
                set_value_at(data, loc, fixed)
            except (KeyError, IndexError, TypeError) as failure:
                raise InvalidOutput(
                    f"{spec.task}: repair could not be applied", fix.text
                ) from failure
            candidate: Any = data
        else:
            candidate = fixed
        try:
            return spec.output_model.model_validate(candidate), False
        except ValidationError as failure:
            raise InvalidOutput(
                f"{spec.task}: still invalid after one repair", fix.text
            ) from failure

    @staticmethod
    def _first_error(model: type[BaseModel], data: Any) -> tuple[tuple[str | int, ...], str] | None:
        if data is None:
            return (), "the answer is not valid JSON"
        try:
            model.model_validate(data)
        except ValidationError as error:
            first = error.errors()[0]
            message = str(first.get("msg", "invalid")).removeprefix("Value error, ")
            return tuple(first.get("loc", ())), message
        return None

    # ------------------------------------------------------------------ admin view

    def status(self) -> dict[str, Any]:
        current = self.store.get()
        providers = []
        for name in ("groq", "gemini"):
            usage = self.quota.usage(name)
            breaker = self.breakers[name].snapshot()
            bucket = self.buckets[name]
            providers.append(
                {
                    "name": name,
                    "model": current.groq_model if name == "groq" else current.gemini_model,
                    "configured": name in self.providers,
                    "breaker": {
                        "state": breaker.state,
                        "failures": breaker.failures,
                        "retry_in_seconds": breaker.retry_in,
                    },  # fmt: skip
                    "minute": {
                        "tokens_used": bucket.used_tokens(),
                        "tokens_limit": bucket.tpm,
                        "requests_used": bucket.used_requests(),
                        "requests_limit": bucket.rpm,
                    },  # fmt: skip
                    "day": {
                        "tokens_used": usage.tokens,
                        "tokens_limit": usage.tokens_limit,
                        "tokens_percent": usage.tokens_percent,
                        "requests_used": usage.requests,
                        "requests_limit": usage.requests_limit,
                        "requests_percent": usage.requests_percent,
                    },  # fmt: skip
                }
            )
        return {"mode": current.mode, "providers": providers}


def _safe_value(data: Any, loc: tuple[str | int, ...]) -> Any:
    try:
        return value_at(data, loc)
    except (KeyError, IndexError, TypeError):
        return None


def _status_for(error: ProviderError) -> str:
    if isinstance(error, ProviderRateLimited):
        return "rate_limited"
    if isinstance(error, ProviderTimeout):
        return "timeout"
    return "error"
