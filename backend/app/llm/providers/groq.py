"""Groq through its OpenAI-compatible endpoint (default model openai/gpt-oss-20b)."""

from __future__ import annotations

import time
from typing import Any

import openai
from openai import OpenAI

from app.llm.errors import (
    OutputTruncated,
    ProviderRateLimited,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.providers.base import (
    int_header,
    parse_duration,
    parse_json,
    retry_after_from_headers,
    schema_name,
)
from app.llm.types import LLMResult, Message


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.groq.com/openai/v1",
        timeout: float = 30.0,
        client: OpenAI | None = None,
        reasoning_effort: str = "low",
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        # The SDK's own retries are off: the gateway owns retry, backoff and failover.
        self._client = client or OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0
        )

    def build_request(
        self, task: str, messages: list[Message], schema: dict[str, Any] | None, max_tokens: int
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_completion_tokens": max_tokens,
            "temperature": 0,
        }
        if "gpt-oss" in self.model and self.reasoning_effort:
            body["extra_body"] = {"reasoning_effort": self.reasoning_effort}
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name(task), "strict": True, "schema": schema},
            }
        return body

    def complete(
        self, task: str, messages: list[Message], schema: dict[str, Any] | None, max_tokens: int
    ) -> LLMResult:
        body = self.build_request(task, messages, schema, max_tokens)
        started = time.perf_counter()
        try:
            raw = self._client.chat.completions.with_raw_response.create(**body)
        except openai.RateLimitError as error:
            headers = getattr(error.response, "headers", None)
            raise ProviderRateLimited(
                "groq rate limited",
                provider=self.name,
                retry_after=retry_after_from_headers(headers),
            ) from error
        except openai.APITimeoutError as error:
            raise ProviderTimeout("groq timed out", provider=self.name) from error
        except openai.APIConnectionError as error:
            raise ProviderUnavailable("groq connection failed", provider=self.name) from error
        except openai.APIStatusError as error:
            if error.status_code >= 500 or error.status_code == 408:
                raise ProviderUnavailable(
                    f"groq error {error.status_code}", provider=self.name,
                    retry_after=retry_after_from_headers(error.response.headers),
                ) from error  # fmt: skip
            raise ProviderRejected(
                f"groq rejected the request ({error.status_code})", provider=self.name
            ) from error

        response = raw.parse()
        headers = raw.headers
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise OutputTruncated("groq output hit the token limit", provider=self.name)
        text = choice.message.content or ""
        usage = response.usage
        details = getattr(usage, "prompt_tokens_details", None)
        return LLMResult(
            text=text,
            json=parse_json(text),
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            cached_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
            provider=self.name,
            model=self.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            remaining_tokens=int_header(headers, "x-ratelimit-remaining-tokens"),
            reset_seconds=parse_duration(headers.get("x-ratelimit-reset-tokens")),
        )
