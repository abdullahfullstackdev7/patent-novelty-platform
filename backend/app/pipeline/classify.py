"""Local classification of element/passage pairs, confidence and excerpt selection.

Everything here is deterministic and free. Only the ambiguous middle band reaches the LLM.
"""

from __future__ import annotations

import re

from app.config import Settings
from app.pipeline.textsplit import sentence_spans
from app.search.ranking import STOPWORDS

DISCLOSED = "disclosed"
PARTIAL = "partial"
NOT_FOUND = "not_found"
STATUS_FROM_LLM = {"d": DISCLOSED, "p": PARTIAL, "n": NOT_FOUND}
EXCERPT_WORDS = 40

_TOKEN = re.compile(r"[a-z][a-z0-9-]{2,}")
_SUFFIXES = ("ing", "ed", "es", "s")


def _stem(token: str) -> str:
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def content_tokens(text: str) -> set[str]:
    return {_stem(t) for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS}


def keyword_overlap(element: str, passage: str) -> float:
    """Share of the element's content words that also occur in the passage (0 to 1)."""
    wanted = content_tokens(element)
    if not wanted:
        return 0.0
    return len(wanted & content_tokens(passage)) / len(wanted)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def pre_classify(score: float, overlap: float, settings: Settings) -> str | None:
    """Local verdict, or None when the pair is ambiguous and needs the LLM.

    Below the low threshold the element is not found. Above the high threshold with enough
    shared keywords it is disclosed. Both stay machine-labelled in the chart.
    """
    if score < settings.pipeline_low_threshold:
        return NOT_FOUND
    if score > settings.pipeline_high_threshold and overlap >= settings.pipeline_keyword_overlap:
        return DISCLOSED
    return None


def local_fallback(score: float, settings: Settings) -> str:
    """Verdict for an ambiguous pair when no LLM can be used."""
    return PARTIAL if score >= settings.pipeline_fallback_partial else NOT_FOUND


def confidence(status: str, score: float, settings: Settings) -> float:
    """Confidence 0 to 1 derived from the best cosine similarity of the element's passages."""
    low, high = settings.pipeline_low_threshold, settings.pipeline_high_threshold
    position = clamp((score - low) / (high - low))
    if status == DISCLOSED:
        value = 0.55 + 0.4 * position
    elif status == PARTIAL:
        value = 0.45 + 0.3 * position
    else:
        value = 0.55 + 0.35 * clamp(1 - score / high)
    return round(value, 3)


def downgrade(status: str) -> str:
    """One step down for a cell whose citation could not be verified."""
    return PARTIAL if status == DISCLOSED else status


def best_excerpt(
    passage: str, element: str, max_words: int = EXCERPT_WORDS
) -> tuple[str, int, int]:
    """The sentence of `passage` that shares most with `element`, as an exact substring.

    Returns (excerpt, start, end) with offsets inside `passage`.
    """
    spans = sentence_spans(passage) or [(0, len(passage))]
    wanted = content_tokens(element)
    best = max(
        spans, key=lambda span: (len(wanted & content_tokens(passage[span[0] : span[1]])), -span[0])
    )
    start, end = best
    words = list(re.finditer(r"\S+", passage[start:end]))
    if len(words) > max_words:
        end = start + words[max_words - 1].end()
    return passage[start:end], start, end


def excerpt_is_verbatim(
    excerpt: str | None, source: str, start: int | None, end: int | None
) -> bool:
    """Server-side check: the excerpt is non-empty and equals source[start:end] exactly."""
    if not excerpt or start is None or end is None:
        return False
    return 0 <= start < end <= len(source) and source[start:end] == excerpt
