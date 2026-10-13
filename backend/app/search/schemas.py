from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class DisclosureQuery:
    """Search input. `priority_date` bounds prior art: only earlier publications are returned."""

    title: str
    summary: str
    elements: list[str]
    priority_date: date
    cpc_prefix: str | None = None
    sources: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ChunkMatch:
    chunk_id: str
    chunk_type: str
    claim_number: int | None
    text: str
    score: float


@dataclass
class SearchHit:
    patent_id: str
    title: str
    source: str
    assignee: str | None
    publication_date: date
    cpc_subclasses: list[str]
    url: str | None
    score: float
    fused_score: float
    rerank_score: float | None
    matched_chunks: list[ChunkMatch] = field(default_factory=list)

    @property
    def matched_chunk_ids(self) -> list[str]:
        return [match.chunk_id for match in self.matched_chunks]


@dataclass(frozen=True)
class CpcSuggestion:
    subclass: str
    votes: int


@dataclass
class SearchResponse:
    hits: list[SearchHit]
    suggested_cpc: list[CpcSuggestion]
    timings_ms: dict[str, float]
