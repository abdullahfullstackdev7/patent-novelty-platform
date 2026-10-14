"""Intake: extract disclosure elements with one LLM call, or locally when no LLM may be used."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from app.llm import prompts
from app.llm.errors import AllProvidersUnavailable, InvalidOutput, LocalOnly, PromptTooLarge
from app.llm.gateway import LLMGateway
from app.pipeline.textsplit import sentence_spans

MAX_ELEMENTS = 10
MIN_WORDS = 3
MAX_WORDS = 25
_CLAUSE_SPLIT = re.compile(r";\s+|,\s+(?:and|wherein|whereby|which|further)\s+|\s+and\s+then\s+")


@dataclass
class Extraction:
    elements: list[str]
    source: str  # llm | local
    tokens: int = 0
    provider: str | None = None
    cache_hit: bool = False
    fallback_reason: str | None = None


def local_elements(problem: str, solution: str) -> list[str]:
    """Deterministic fallback: clauses of the solution, then of the problem, as short phrases."""
    found: list[str] = []
    seen: set[str] = set()
    for text in (solution, problem):
        for start, end in sentence_spans(text):
            for clause in _CLAUSE_SPLIT.split(text[start:end]):
                words = clause.strip(" .;:,").split()
                if len(words) < MIN_WORDS:
                    continue
                phrase = " ".join(words[:MAX_WORDS])
                key = phrase.lower()
                if key not in seen:
                    seen.add(key)
                    found.append(phrase)
        if len(found) >= 3:
            break
    return found[:MAX_ELEMENTS]


def extract_elements(
    gateway: LLMGateway | None,
    *,
    title: str,
    technical_field: str,
    problem: str,
    solution: str,
    case_id: uuid.UUID | None = None,
    case_mode: str = "auto",
) -> Extraction:
    """One LLM call (stable system prompt, strict schema). Falls back to local clauses."""
    reason = "no gateway"
    if gateway is not None:
        user = prompts.parse_elements_user(title, technical_field, problem, solution)
        try:
            out = gateway.run(prompts.PARSE_ELEMENTS, user, case_id=case_id, case_mode=case_mode)
            return Extraction(
                [e.text for e in out.value.elements],
                "llm",
                out.total_tokens,
                out.provider,
                out.cache_hit,
            )
        except LocalOnly:
            reason = "local_only"
        except (AllProvidersUnavailable, PromptTooLarge, InvalidOutput) as failure:
            reason = type(failure).__name__
    return Extraction(local_elements(problem, solution), "local", fallback_reason=reason)
