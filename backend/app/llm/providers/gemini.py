"""Google Gemini through the google-genai SDK (model id comes from GEMINI_MODEL)."""

from __future__ import annotations

import time
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.llm.errors import (
    OutputTruncated,
    ProviderRateLimited,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.providers.base import parse_json, retry_after_from_text
from app.llm.types import LLMResult, Message


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        thinking_level: str = "minimal",
        client: genai.Client | None = None,
    ) -> None:
        self.model = model
        self.thinking_level = thinking_level
        self._client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000))
        )

    def build_config(
        self, messages: list[Message], schema: dict[str, Any] | None, max_tokens: int
    ) -> types.GenerateContentConfig:
        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        config: dict[str, Any] = {
            "system_instruction": system,
            "temperature": 0,
            "max_output_tokens": max_tokens,
        }
        if schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = schema
        if self.thinking_level:  # keep hidden reasoning, and its cost, as small as possible
            config["thinking_config"] = types.ThinkingConfig(
                thinking_level=self.thinking_level.upper()
            )
        return types.GenerateContentConfig(**config)

    @staticmethod
    def build_contents(messages: list[Message]) -> list[types.Content]:
        roles = {"user": "user", "assistant": "model"}
        return [
            types.Content(role=roles[m.role], parts=[types.Part(text=m.content)])
            for m in messages
            if m.role != "system"
        ]

    def complete(
        self, task: str, messages: list[Message], schema: dict[str, Any] | None, max_tokens: int
    ) -> LLMResult:
        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=self.build_contents(messages),
                config=self.build_config(messages, schema, max_tokens),
            )
        except errors.ClientError as error:
            code = int(getattr(error, "code", 0) or 0)
            if code == 429:
                raise ProviderRateLimited(
                    "gemini rate limited", provider=self.name,
                    retry_after=retry_after_from_text(str(error)),
                ) from error  # fmt: skip
            if code == 408:
                raise ProviderTimeout("gemini timed out", provider=self.name) from error
            raise ProviderRejected(
                f"gemini rejected the request ({code})", provider=self.name
            ) from error
        except errors.ServerError as error:
            raise ProviderUnavailable(
                f"gemini error {getattr(error, 'code', '')}", provider=self.name,
                retry_after=retry_after_from_text(str(error)),
            ) from error  # fmt: skip
        except httpx.TimeoutException as error:
            raise ProviderTimeout("gemini timed out", provider=self.name) from error
        except (httpx.TransportError, errors.APIError) as error:
            raise ProviderUnavailable("gemini connection failed", provider=self.name) from error

        candidates = response.candidates or []
        finish = getattr(candidates[0], "finish_reason", None) if candidates else None
        if finish is not None and getattr(finish, "name", str(finish)) == "MAX_TOKENS":
            raise OutputTruncated("gemini output hit the token limit", provider=self.name)
        try:
            text = response.text or ""
        except Exception:  # blocked or empty candidates
            text = ""
        usage = response.usage_metadata
        thoughts = (getattr(usage, "thoughts_token_count", 0) or 0) if usage else 0
        return LLMResult(
            text=text,
            json=parse_json(text),
            tokens_in=(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0,
            # Hidden thinking tokens are billed and counted like output tokens.
            tokens_out=((getattr(usage, "candidates_token_count", 0) or 0) + thoughts)
            if usage
            else 0,
            cached_tokens=(getattr(usage, "cached_content_token_count", 0) or 0) if usage else 0,
            provider=self.name,
            model=self.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
