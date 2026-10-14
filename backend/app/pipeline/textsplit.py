"""Exact-substring text spans: windows of at most N words and sentence spans."""

from __future__ import annotations

import re

_WORD = re.compile(r"\S+")
_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+")
_BOUNDARY_SUFFIXES = (".", ";", ":", "!", "?")


def split_windows(text: str, max_words: int) -> list[tuple[int, int]]:
    """Spans (start, end) covering `text`, each at most `max_words` words.

    Cuts prefer a sentence or clause end in the last third of a window, otherwise they fall
    on a word boundary. `text[start:end]` is always an exact substring.
    """
    words = list(_WORD.finditer(text))
    if not words:
        return []
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(words):
        j = min(i + max_words, len(words))
        if j < len(words):
            floor = i + (max_words * 2) // 3
            for k in range(j, floor, -1):
                if words[k - 1].group().endswith(_BOUNDARY_SUFFIXES):
                    j = k
                    break
        spans.append((words[i].start(), words[j - 1].end()))
        i = j
    return spans


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Spans of sentences or clauses, trimmed of surrounding whitespace."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text.rstrip())))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def word_count(text: str) -> int:
    return len(text.split())
