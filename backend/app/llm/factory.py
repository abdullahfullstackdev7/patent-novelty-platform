"""Build the process-wide gateway from settings. A provider without an API key is left out."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.llm.gateway import LLMGateway
from app.llm.store import CallRecorder, LlmSettingsStore, QuotaTracker, ResponseCache


def build_gateway(settings: Settings, sessions: sessionmaker[Session]) -> LLMGateway:
    # Provider SDKs are imported here so that importing the API does not load them.
    providers = {}
    if settings.groq_api_key:
        from app.llm.providers.groq import GroqProvider

        providers["groq"] = GroqProvider(
            settings.groq_api_key,
            settings.groq_model,
            base_url=settings.groq_base_url,
            timeout=settings.llm_timeout_seconds,
        )
    if settings.gemini_api_key:
        from app.llm.providers.gemini import GeminiProvider

        providers["gemini"] = GeminiProvider(
            settings.gemini_api_key,
            settings.gemini_model,
            timeout=settings.llm_timeout_seconds,
            thinking_level=settings.gemini_thinking_level,
        )
    return LLMGateway(
        providers,
        settings,
        LlmSettingsStore(sessions, settings),
        ResponseCache(sessions, settings),
        CallRecorder(sessions),
        QuotaTracker(sessions, settings),
    )
