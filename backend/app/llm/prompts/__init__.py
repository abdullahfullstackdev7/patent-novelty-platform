"""Versioned prompt library.

Each task has a system prompt file `<task>_v<N>.txt` (stable text, so provider prompt caching
applies), an output model and a token cap. User messages are rendered here from structured
data, with every untrusted passage quoted as a data block. Rendering is covered by golden
tests: a prompt change must be deliberate, bump the version and update the golden file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.llm.prompts.models import ChartOut, ParseElementsOut, SummaryOut
from app.llm.types import Message
from app.security.prompt import quote_untrusted

PROMPT_DIR = Path(__file__).parent
MAX_DISCLOSURE_WORDS = 1500


@dataclass(frozen=True)
class PromptSpec:
    task: str
    version: int
    output_model: type[BaseModel]
    max_tokens: int

    @property
    def schema_version(self) -> str:
        """Part of the cache key: changes whenever the prompt or the output shape changes."""
        return f"{self.task}@v{self.version}"

    @property
    def system(self) -> str:
        return (PROMPT_DIR / f"{self.task}_v{self.version}.txt").read_text(encoding="utf-8").strip()

    def messages(self, user: str) -> list[Message]:
        return [Message("system", self.system), Message("user", user)]


# Output caps follow the token budget in the plan (section 3).
PARSE_ELEMENTS = PromptSpec("parse_elements", 1, ParseElementsOut, max_tokens=500)
CHART_CELLS = PromptSpec("chart_cells", 1, ChartOut, max_tokens=900)
EXEC_SUMMARY = PromptSpec("exec_summary", 1, SummaryOut, max_tokens=500)

PROMPTS: dict[str, PromptSpec] = {p.task: p for p in (PARSE_ELEMENTS, CHART_CELLS, EXEC_SUMMARY)}


def _cap_words(text: str, limit: int) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit])


def parse_elements_user(title: str, technical_field: str, problem: str, solution: str) -> str:
    """One data block with the disclosure, capped at 1,500 words as the token plan requires."""
    body = "\n".join(
        [
            f"Title: {title}",
            f"Field: {technical_field}",
            f"Problem: {problem}",
            f"Solution: {solution}",
        ]
    )
    return quote_untrusted("disclosure", _cap_words(body, MAX_DISCLOSURE_WORDS))


def chart_cells_user(reference_id: str, items: list[dict[str, Any]]) -> str:
    """Compact JSON of the ambiguous elements and their top passages for one reference.

    items: [{"e": "E1", "t": "element text", "ps": [{"id": "...", "t": "passage text"}]}]
    """
    payload = {"ref": reference_id, "items": items}
    return quote_untrusted(
        "reference", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def exec_summary_user(facts: dict[str, Any]) -> str:
    """Statuses and ids only, never passage text."""
    return quote_untrusted(
        "facts", json.dumps(facts, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )
