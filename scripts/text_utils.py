"""Text cleaning, claim parsing and passage chunking for the corpus build.

All chunk offsets index into the cleaned text returned by `clean_text`, and every chunk text
is an exact substring of that cleaned text, which keeps later excerpt validation simple.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_DASHES = str.maketrans({chr(0x2013): "-", chr(0x2014): "-", chr(0x2212): "-"})
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_SPACE = re.compile(r"\s+")
_LEADING_BOILERPLATE = re.compile(
    r"^\s*(?:what\s+is\s+claimed\s+is|we\s+claim|i\s+claim|the\s+invention\s+claimed\s+is"
    r"|claims?)\s*[:.]?\s*",
    re.IGNORECASE,
)
_CLAIM_MARKER = re.compile(
    r"(?:(?<=\s)|^)(\d{1,3})(?:\s*\.?\s*-\s*(\d{1,3}))?\s*\.\s+(?=[A-Za-z(\"'\[])"
)
_CANCELED = re.compile(
    r"^\(?\s*(?:canceled|cancelled|deleted|withdrawn|cancelled without prejudice"
    r"|canceled without prejudice)\s*\)?\s*\.?$",
    re.IGNORECASE,
)
_CLAIM_REF = re.compile(r"\bclaims?\s+(\d{1,3})\b", re.IGNORECASE)
_ABBREVIATIONS = (
    "fig",
    "figs",
    "no",
    "nos",
    "e.g",
    "i.e",
    "et al",
    "etc",
    "vs",
    "approx",
    "ca",
    "cf",
    "col",
    "sec",
    "ser",
    "u.s",
    "dr",
    "inc",
    "co",
    "ltd",
)
_SENTENCE_END = re.compile(r"([.!?]+[\"')\]]*)(\s+)(?=[A-Z0-9(\"'\[])")


def clean_text(text: str | None) -> str:
    """Normalize unicode (long dashes become hyphens), drop control characters, collapse spaces."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_DASHES)
    text = _CONTROL.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


@dataclass(frozen=True)
class Claim:
    number: int
    text: str
    is_independent: bool
    parent: int | None


def strip_claim_numbering(text: str, number: int | None = None) -> str:
    """Remove a leading `N.` marker (and 'What is claimed is:' boilerplate) from claim text."""
    text = _LEADING_BOILERPLATE.sub("", text.strip(), count=1)
    pattern = rf"^\(?{number}\)?\s*[.)]\s*" if number is not None else r"^\(?\d{1,3}\)?\s*[.)]\s+"
    return re.sub(pattern, "", text, count=1).strip()


def classify_claim(number: int, text: str) -> tuple[bool, int | None]:
    """A claim is dependent when its opening words reference an earlier claim."""
    for match in _CLAIM_REF.finditer(text[:300]):
        parent = int(match.group(1))
        if parent < number:
            return False, parent
    return True, None


def parse_claims(raw: str | None) -> list[Claim]:
    """Split a single claims blob ('1. A method ... 2. The method of claim 1 ...') into claims.

    Markers are accepted only when they continue the sequence, so numbers inside claim bodies
    such as 'of claim 1. 2.5 mm' do not create false splits. The first marker may start above 1
    (amended claim sets) and range markers such as '1-20. (canceled)' advance the sequence.
    Canceled claims are dropped, so surviving claim numbers can have gaps.
    """
    text = clean_text(raw)
    text = _LEADING_BOILERPLATE.sub("", text, count=1)
    if not text:
        return []
    marks: list[tuple[int, int, int]] = []  # (number, marker start, body start)
    expected: int | None = None
    for match in _CLAIM_MARKER.finditer(text):
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        if expected is None:
            if match.start() != 0:
                continue
        elif first != expected or last < first:
            continue
        marks.append((first, match.start(), match.end()))
        expected = last + 1
    if not marks:
        body = text.strip()
        independent, parent = classify_claim(1, body)
        return [Claim(1, body, independent, parent)] if body else []
    claims: list[Claim] = []
    for index, (number, _start, body_start) in enumerate(marks):
        end = marks[index + 1][1] if index + 1 < len(marks) else len(text)
        body = text[body_start:end].strip()
        if not body or _CANCELED.match(body):
            continue
        independent, parent = classify_claim(number, body)
        claims.append(Claim(number, body, independent, parent))
    # a claim whose parent was canceled stands alone, so treat it as independent
    kept = {claim.number for claim in claims}
    return [
        claim
        if claim.parent is None or claim.parent in kept
        else Claim(claim.number, claim.text, True, None)
        for claim in claims
    ]


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of sentences, skipping common patent abbreviations."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        before = text[start : match.start(1) + 1]
        last_word = re.findall(r"[A-Za-z.]+$", before.rstrip(".!?\"')]") + "")
        token = (last_word[0] if last_word else "").lower().rstrip(".")
        if match.group(1) == "." and token in _ABBREVIATIONS:
            continue
        end = match.end(1)
        spans.append((start, end))
        start = match.end(2)
    if start < len(text):
        spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _word_count(text: str) -> int:
    return len(text.split())


def chunk_passages(
    text: str, min_words: int = 80, max_words: int = 150, drop_below: int = 15
) -> list[tuple[str, int, int]]:
    """Pack whole sentences into passages of min_words to max_words (cleaned text expected).

    Returns (passage, char_start, char_end). A sentence longer than max_words is cut at word
    boundaries. A short trailing remainder is merged into the previous passage when it fits.
    Passages still under `drop_below` words (figure labels, stray markup) are discarded.
    """
    pieces: list[tuple[int, int]] = []
    for start, end in split_sentences(text):
        if _word_count(text[start:end]) <= max_words:
            pieces.append((start, end))
            continue
        words = list(re.finditer(r"\S+", text[start:end]))
        for i in range(0, len(words), max_words):
            group = words[i : i + max_words]
            pieces.append((start + group[0].start(), start + group[-1].end()))

    passages: list[tuple[int, int]] = []
    current: tuple[int, int] | None = None
    for start, end in pieces:
        if current is None:
            current = (start, end)
            continue
        merged_words = _word_count(text[current[0] : end])
        if merged_words <= max_words and _word_count(text[current[0] : current[1]]) < min_words:
            current = (current[0], end)
        else:
            passages.append(current)
            current = (start, end)
    if current is not None:
        if (
            passages
            and _word_count(text[current[0] : current[1]]) < min_words
            and _word_count(text[passages[-1][0] : current[1]]) <= max_words
        ):
            passages[-1] = (passages[-1][0], current[1])
        else:
            passages.append(current)
    return [(text[s:e], s, e) for s, e in passages if _word_count(text[s:e]) >= drop_below]
