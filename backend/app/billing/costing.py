"""Modelled cost of LLM tokens and infrastructure.

The prices are reference assumptions kept in settings (PRICE_*), not quotes. They put a cost
next to the free-tier usage so the margin trend shows what a paid plan would cost.
"""

from __future__ import annotations

from app.config import Settings


def token_cost(settings: Settings, provider: str, tokens_in: int, tokens_out: int) -> float:
    prices = {
        "groq": (settings.price_groq_in_per_mtok, settings.price_groq_out_per_mtok),
        "gemini": (settings.price_gemini_in_per_mtok, settings.price_gemini_out_per_mtok),
    }
    price_in, price_out = prices.get(provider, (0.0, 0.0))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def price_params(settings: Settings) -> dict[str, float]:
    """Bind parameters for SQL that costs tokens per provider."""
    return {
        "g_in": settings.price_groq_in_per_mtok,
        "g_out": settings.price_groq_out_per_mtok,
        "m_in": settings.price_gemini_in_per_mtok,
        "m_out": settings.price_gemini_out_per_mtok,
    }


# SQL expression for the modelled cost of the rows of llm_calls aliased `l`.
TOKEN_COST_SQL = (
    "(CASE l.provider WHEN 'groq' THEN l.tokens_in * :g_in + l.tokens_out * :g_out "
    "WHEN 'gemini' THEN l.tokens_in * :m_in + l.tokens_out * :m_out ELSE 0 END) / 1000000.0"
)
