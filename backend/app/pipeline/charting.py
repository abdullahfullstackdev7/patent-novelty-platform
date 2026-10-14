"""Claim charting for one reference: local verdicts first, one batched LLM call for the rest."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass

from app.config import Settings
from app.llm import prompts
from app.llm.budget import estimate_tokens
from app.llm.errors import AllProvidersUnavailable, InvalidOutput, LocalOnly, PromptTooLarge
from app.llm.gateway import LLMGateway
from app.pipeline import classify
from app.pipeline.passages import Passage

logger = logging.getLogger("priorart.pipeline")
ELEMENT_WORDS = 60  # element text sent to the model is capped at this many words
BATCH_MARGIN_TOKENS = 100


@dataclass
class CellDraft:
    element: str
    status: str
    confidence: float
    passage: Passage | None
    excerpt: str | None
    char_start: int | None  # offsets of the excerpt inside the text of passage.chunk_id
    char_end: int | None
    rationale: str | None
    method: str  # local | llm
    input_hash: str


@dataclass
class ChartingStats:
    tokens: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    local_cells: int = 0
    llm_cells: int = 0
    fallback_cells: int = 0
    downgraded: int = 0
    llm_used: bool = False
    provider: str | None = None
    error: str | None = None

    def merge(self, other: ChartingStats) -> None:
        for name in ("tokens", "llm_calls", "cache_hits", "local_cells", "llm_cells",
                     "fallback_cells", "downgraded"):  # fmt: skip
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.llm_used = self.llm_used or other.llm_used
        self.provider = other.provider or self.provider
        self.error = other.error or self.error


def cell_input_hash(element_text: str, passages: list[Passage], settings: Settings) -> str:
    """Everything the cell depends on. An unchanged hash means the cell need not be recomputed."""
    payload = [
        element_text,
        [[p.chunk_id, p.char_start, p.char_end, hashlib.sha256(p.text.encode()).hexdigest()]
         for p in passages],
        [settings.pipeline_low_threshold, settings.pipeline_high_threshold,
         settings.pipeline_keyword_overlap, settings.pipeline_fallback_partial],
        prompts.CHART_CELLS.schema_version,
    ]  # fmt: skip
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def make_cell(
    element: str,
    element_text: str,
    status: str,
    passage: Passage | None,
    rationale: str | None,
    method: str,
    settings: Settings,
    input_hash: str,
    penalty: float = 1.0,
) -> CellDraft:
    score = passage.score if passage else 0.0
    value = round(classify.confidence(status, score, settings) * penalty, 3)
    excerpt = start = end = None
    if passage is not None:
        excerpt, rel_start, rel_end = classify.best_excerpt(passage.text, element_text)
        start, end = passage.char_start + rel_start, passage.char_start + rel_end
    return CellDraft(
        element, status, value, passage, excerpt, start, end, rationale, method, input_hash
    )


def _cap_words(text: str, limit: int) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit])


def _batches(items: list[dict], budget_tokens: int) -> list[list[dict]]:
    """Split items so each request stays inside the per-request token budget."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    used = 0
    for item in items:
        cost = estimate_tokens(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        if current and used + cost > budget_tokens:
            batches.append(current)
            current, used = [], 0
        current.append(item)
        used += cost
    if current:
        batches.append(current)
    return batches


def chart_reference(
    gateway: LLMGateway | None,
    reference_id: str,
    elements: dict[str, str],  # element key -> text, only the ones to (re)compute
    picks: dict[str, list[Passage]],
    settings: Settings,
    *,
    case_id: uuid.UUID | None = None,
    case_mode: str = "auto",
) -> tuple[dict[str, CellDraft], ChartingStats]:
    stats = ChartingStats()
    drafts: dict[str, CellDraft] = {}
    ambiguous: list[str] = []

    for key, text in elements.items():
        passages = picks.get(key, [])
        digest = cell_input_hash(text, passages, settings)
        if not passages:
            drafts[key] = make_cell(
                key, text, classify.NOT_FOUND, None, None, "local", settings, digest
            )
            stats.local_cells += 1
            continue
        top = passages[0]
        verdict = classify.pre_classify(
            top.score, classify.keyword_overlap(text, top.text), settings
        )
        if verdict is None:
            ambiguous.append(key)
            continue
        drafts[key] = make_cell(key, text, verdict, top, None, "local", settings, digest)
        stats.local_cells += 1

    if ambiguous:
        resolved = _ask_llm(gateway, reference_id, ambiguous, elements, picks, settings,
                            case_id, case_mode, stats)  # fmt: skip
        for key in ambiguous:
            text, passages = elements[key], picks[key]
            digest = cell_input_hash(text, passages, settings)
            if key in resolved:
                drafts[key] = resolved[key](digest)
                stats.llm_cells += 1
            else:
                status = classify.local_fallback(passages[0].score, settings)
                drafts[key] = make_cell(
                    key, text, status, passages[0], None, "local", settings, digest
                )
                stats.fallback_cells += 1
    return drafts, stats


def _ask_llm(
    gateway: LLMGateway | None,
    reference_id: str,
    keys: list[str],
    elements: dict[str, str],
    picks: dict[str, list[Passage]],
    settings: Settings,
    case_id: uuid.UUID | None,
    case_mode: str,
    stats: ChartingStats,
) -> dict[str, callable]:
    """Returns key -> factory(input_hash) -> CellDraft for every element the model answered."""
    if gateway is None:
        stats.error = "no gateway"
        return {}
    spec = prompts.CHART_CELLS
    lookups: dict[str, dict[str, Passage]] = {}
    items = []
    for key in keys:
        local_ids = {f"{key}.{n}": p for n, p in enumerate(picks[key], start=1)}
        lookups[key] = local_ids
        items.append({
            "e": key,
            "t": _cap_words(elements[key], ELEMENT_WORDS),
            "ps": [{"id": pid, "t": p.text} for pid, p in local_ids.items()],
        })  # fmt: skip
    overhead = estimate_tokens(spec.system) + spec.max_tokens + BATCH_MARGIN_TOKENS
    budget = max(settings.llm_max_request_tokens - overhead, 200)

    resolved: dict[str, callable] = {}
    for batch in _batches(items, budget):
        try:
            out = gateway.run(spec, prompts.chart_cells_user(reference_id, batch),
                              case_id=case_id, case_mode=case_mode)  # fmt: skip
        except LocalOnly:
            stats.error = "local_only"
            return resolved
        except (AllProvidersUnavailable, PromptTooLarge, InvalidOutput) as failure:
            stats.error = type(failure).__name__
            logger.warning("charting fell back to local rules: %s", type(failure).__name__)
            continue
        stats.llm_used = True
        stats.tokens += out.total_tokens
        stats.llm_calls += len(out.calls)
        stats.cache_hits += int(out.cache_hit)
        stats.provider = out.provider or stats.provider
        for cell in out.value.cells:
            if cell.e not in lookups or cell.e in resolved:
                continue
            resolved[cell.e] = _cell_factory(
                cell, lookups[cell.e], elements[cell.e], picks[cell.e], settings, stats
            )
    return resolved


def _cell_factory(cell, lookup, element_text, passages, settings, stats):
    """Turn one model answer into a CellDraft, verifying the cited passage."""
    status = classify.STATUS_FROM_LLM[cell.s]
    cited = lookup.get(cell.p)
    penalty = 1.0
    if cited is None:
        cited = passages[0]
        if status != classify.NOT_FOUND:
            # The model cited a passage it was not given. Do not trust the verdict fully.
            status = classify.downgrade(status)
            penalty = 0.5
            stats.downgraded += 1

    def build(digest: str) -> CellDraft:
        return make_cell(
            cell.e, element_text, status, cited, cell.r or None, "llm", settings, digest, penalty
        )

    return build
