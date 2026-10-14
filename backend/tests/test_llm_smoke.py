"""One real call per provider. Run by hand or in the manual CI job:

    GROQ_API_KEY=... GEMINI_API_KEY=... uv run pytest -m smoke -s

Skipped when the key is missing. Each call is tiny (a few hundred tokens).
"""

from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.groq import GroqProvider
from app.llm.types import Message

pytestmark = pytest.mark.smoke

SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
    "additionalProperties": False,
}
MESSAGES = [
    Message("system", 'Answer with JSON only: {"status":"ok"}'),
    Message("user", "Report your status."),
]


def need(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def test_groq_returns_schema_valid_json_and_token_counts():
    settings = Settings()
    provider = GroqProvider(
        need("GROQ_API_KEY"), settings.groq_model, base_url=settings.groq_base_url
    )
    result = provider.complete("smoke", MESSAGES, SCHEMA, 400)
    print(f"groq {result.model}: in={result.tokens_in} out={result.tokens_out} "
          f"remaining={result.remaining_tokens} {result.latency_ms} ms")  # fmt: skip
    assert result.json == {"status": "ok"}
    assert result.tokens_in > 0 and result.tokens_out > 0
    assert result.remaining_tokens is not None  # rate-limit headers are present


def test_gemini_returns_schema_valid_json_and_token_counts():
    settings = Settings()
    provider = GeminiProvider(
        need("GEMINI_API_KEY"), settings.gemini_model, thinking_level=settings.gemini_thinking_level
    )
    result = provider.complete("smoke", MESSAGES, SCHEMA, 400)
    print(
        f"gemini {result.model}: in={result.tokens_in} out={result.tokens_out} {result.latency_ms} ms"
    )
    assert result.json == {"status": "ok"}
    assert result.tokens_in > 0 and result.tokens_out > 0
