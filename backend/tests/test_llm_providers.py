"""Provider adapters against mocked HTTP transport / SDK clients. No network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from openai import OpenAI

from app.llm.errors import (
    OutputTruncated,
    ProviderRateLimited,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.prompts import CHART_CELLS
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.groq import GroqProvider
from app.llm.schema import provider_schema
from app.llm.types import Message

SCHEMA = provider_schema(CHART_CELLS.output_model)
MESSAGES = [Message("system", "You are strict."), Message("user", "Compare these.")]
ANSWER = {"cells": [{"e": "E1", "s": "d", "p": "P1", "r": "matches"}]}


# ---- Groq ---------------------------------------------------------------------


def groq_with(handler, **kwargs) -> tuple[GroqProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = OpenAI(
        api_key="gsk_unit_test_key",
        base_url="https://api.groq.test/openai/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(recording)),
        max_retries=0,
    )
    return GroqProvider("gsk_unit_test_key", "openai/gpt-oss-20b", client=client, **kwargs), seen


def completion(content=None, finish="stop", usage=None) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "openai/gpt-oss-20b",
        "choices": [
            {"index": 0, "finish_reason": finish,
             "message": {"role": "assistant", "content": json.dumps(ANSWER) if content is None else content}},
        ],
        "usage": usage or {
            "prompt_tokens": 420, "completion_tokens": 60, "total_tokens": 480,
            "prompt_tokens_details": {"cached_tokens": 300},
        },
    }  # fmt: skip


def test_groq_request_body_is_budgeted_deterministic_and_schema_constrained():
    provider, seen = groq_with(lambda r: httpx.Response(200, json=completion()))
    provider.complete("chart_cells", MESSAGES, SCHEMA, 700)
    request = seen[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://api.groq.test/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer gsk_unit_test_key"
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["max_completion_tokens"] == 700  # always set
    assert body["temperature"] == 0
    assert body["reasoning_effort"] == "low"  # gpt-oss reasoning kept small
    assert body["messages"] == [
        {"role": "system", "content": "You are strict."},
        {"role": "user", "content": "Compare these."},
    ]
    schema_format = body["response_format"]
    assert schema_format["type"] == "json_schema"
    assert schema_format["json_schema"]["strict"] is True
    assert schema_format["json_schema"]["name"] == "chart_cells"
    assert schema_format["json_schema"]["schema"] == SCHEMA


def test_groq_omits_reasoning_effort_for_other_models_and_schema_when_absent():
    provider, seen = groq_with(lambda r: httpx.Response(200, json=completion("plain")))
    provider.model = "llama-3.3-70b-versatile"
    result = provider.complete("free_text", MESSAGES, None, 100)
    body = json.loads(seen[0].content)
    assert "reasoning_effort" not in body and "response_format" not in body
    assert result.text == "plain" and result.json is None


def test_groq_parses_tokens_cached_tokens_and_rate_limit_headers():
    headers = {"x-ratelimit-remaining-tokens": "7123", "x-ratelimit-reset-tokens": "2m59.56s"}
    provider, _ = groq_with(lambda r: httpx.Response(200, json=completion(), headers=headers))
    result = provider.complete("chart_cells", MESSAGES, SCHEMA, 700)
    assert result.json == ANSWER and result.provider == "groq"
    assert (result.tokens_in, result.tokens_out, result.cached_tokens) == (420, 60, 300)
    assert result.total_tokens == 480
    assert result.remaining_tokens == 7123 and result.reset_seconds == pytest.approx(179.56)
    assert result.model == "openai/gpt-oss-20b" and result.latency_ms >= 0


def test_groq_maps_http_errors_to_gateway_errors():
    def answering(status, headers=None):
        provider, _ = groq_with(
            lambda r: httpx.Response(status, json={"error": {"message": "x"}}, headers=headers)
        )
        return provider

    with pytest.raises(ProviderRateLimited) as limited:
        answering(429, {"retry-after": "17"}).complete("t", MESSAGES, SCHEMA, 10)
    assert limited.value.retry_after == 17 and limited.value.provider == "groq"
    with pytest.raises(ProviderUnavailable):
        answering(503).complete("t", MESSAGES, SCHEMA, 10)
    with pytest.raises(ProviderUnavailable):
        answering(500).complete("t", MESSAGES, SCHEMA, 10)
    with pytest.raises(ProviderRejected) as rejected:
        answering(400).complete("t", MESSAGES, SCHEMA, 10)
    assert rejected.value.retryable is False and rejected.value.counts_against_breaker is False
    with pytest.raises(ProviderRejected):
        answering(401).complete("t", MESSAGES, SCHEMA, 10)


def test_groq_maps_timeouts_connection_failures_and_truncation():
    def raising(error):
        def handler(request):
            raise error

        return groq_with(handler)[0]

    with pytest.raises(ProviderTimeout):
        raising(httpx.ReadTimeout("slow")).complete("t", MESSAGES, SCHEMA, 10)
    with pytest.raises(ProviderUnavailable):
        raising(httpx.ConnectError("down")).complete("t", MESSAGES, SCHEMA, 10)
    provider, _ = groq_with(lambda r: httpx.Response(200, json=completion('{"cells":[', "length")))
    with pytest.raises(OutputTruncated):
        provider.complete("t", MESSAGES, SCHEMA, 10)


# ---- Gemini -------------------------------------------------------------------


class FakeGenai:
    """Stands in for google.genai.Client: models.generate_content returns or raises."""

    def __init__(self, outcome):
        self.calls: list[dict] = []
        self.outcome = outcome
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def gemini_response(text=None, finish="STOP", usage=None):
    return SimpleNamespace(
        text=json.dumps(ANSWER) if text is None else text,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        usage_metadata=usage
        or SimpleNamespace(
            prompt_token_count=500, candidates_token_count=40, thoughts_token_count=12,
            cached_content_token_count=0,
        ),
    )  # fmt: skip


def test_gemini_request_uses_json_schema_and_minimal_thinking():
    client = FakeGenai(gemini_response())
    provider = GeminiProvider("key", "gemini-3.1-flash-lite", client=client)
    provider.complete("chart_cells", MESSAGES, SCHEMA, 650)
    call = client.calls[0]
    config = call["config"]
    assert call["model"] == "gemini-3.1-flash-lite"
    assert config.system_instruction == "You are strict."
    assert config.max_output_tokens == 650 and config.temperature == 0
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SCHEMA
    assert config.thinking_config.thinking_level == genai_types.ThinkingLevel.MINIMAL
    assert [c.role for c in call["contents"]] == ["user"]  # system goes to system_instruction
    assert call["contents"][0].parts[0].text == "Compare these."


def test_gemini_thinking_config_can_be_disabled_and_roles_are_mapped():
    provider = GeminiProvider(
        "key", "gemini-3.1-flash-lite", thinking_level="", client=FakeGenai(None)
    )
    config = provider.build_config(MESSAGES, None, 100)
    assert config.thinking_config is None and config.response_json_schema is None
    contents = provider.build_contents(
        [Message("user", "a"), Message("assistant", "b"), Message("system", "ignored")]
    )
    assert [c.role for c in contents] == ["user", "model"]


def test_gemini_counts_thinking_tokens_as_output_and_parses_json():
    provider = GeminiProvider("key", "gemini-3.1-flash-lite", client=FakeGenai(gemini_response()))
    result = provider.complete("chart_cells", MESSAGES, SCHEMA, 650)
    assert result.json == ANSWER and result.provider == "gemini"
    assert (result.tokens_in, result.tokens_out) == (500, 52)  # 40 answer + 12 thinking
    assert result.remaining_tokens is None and result.model == "gemini-3.1-flash-lite"


def test_gemini_maps_errors():
    def failing(error):
        return GeminiProvider("key", "gemini-3.1-flash-lite", client=FakeGenai(error))

    quota = genai_errors.ClientError(
        429, {"error": {"code": 429, "message": "Quota exceeded. Please retry in 34.5s.",
                        "status": "RESOURCE_EXHAUSTED"}}
    )  # fmt: skip
    with pytest.raises(ProviderRateLimited) as limited:
        failing(quota).complete("t", MESSAGES, SCHEMA, 10)
    assert limited.value.retry_after == 34.5

    bad = genai_errors.ClientError(400, {"error": {"code": 400, "message": "bad schema"}})
    with pytest.raises(ProviderRejected):
        failing(bad).complete("t", MESSAGES, SCHEMA, 10)
    down = genai_errors.ServerError(503, {"error": {"code": 503, "message": "overloaded"}})
    with pytest.raises(ProviderUnavailable):
        failing(down).complete("t", MESSAGES, SCHEMA, 10)
    with pytest.raises(ProviderTimeout):
        failing(httpx.ReadTimeout("slow")).complete("t", MESSAGES, SCHEMA, 10)
    with pytest.raises(ProviderUnavailable):
        failing(httpx.ConnectError("down")).complete("t", MESSAGES, SCHEMA, 10)
    with pytest.raises(OutputTruncated):
        GeminiProvider(
            "key", "gemini-3.1-flash-lite", client=FakeGenai(gemini_response("{", "MAX_TOKENS"))
        ).complete("t", MESSAGES, SCHEMA, 10)


def test_gemini_blocked_response_yields_empty_text_not_a_crash():
    class Blocked(SimpleNamespace):
        @property
        def text(self):
            raise ValueError("response blocked")

    blocked = Blocked(
        candidates=[], usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=0,
                                                       thoughts_token_count=0, cached_content_token_count=0)
    )  # fmt: skip
    result = GeminiProvider("key", "m", client=FakeGenai(blocked)).complete(
        "t", MESSAGES, SCHEMA, 10
    )
    assert result.text == "" and result.json is None
