"""Passage selection: for each element, the two most similar passages of a reference."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PatentChunk
from app.pipeline.textsplit import split_windows
from app.search.embedding import Embedder

CHUNK_TYPES = ("claim", "abstract", "summary")


@dataclass(frozen=True)
class Passage:
    """A piece of one chunk of at most N words. `text == chunk_text[char_start:char_end]`."""

    chunk_id: str
    patent_id: str
    chunk_type: str
    claim_number: int | None
    text: str
    char_start: int
    char_end: int
    score: float = 0.0


@dataclass(frozen=True)
class ChunkRow:
    id: str
    type: str
    claim_number: int | None
    text: str
    embedding: np.ndarray | None


def load_chunks(session: Session, patent_id: str) -> list[ChunkRow]:
    """Claims, abstract and summary passages of a reference, in a stable order."""
    rows = session.execute(
        select(
            PatentChunk.id,
            PatentChunk.type,
            PatentChunk.claim_number,
            PatentChunk.text,
            PatentChunk.embedding,
        )
        .where(PatentChunk.patent_id == patent_id, PatentChunk.type.in_(CHUNK_TYPES))
        .order_by(PatentChunk.type, PatentChunk.seq)
    ).all()
    return [
        ChunkRow(r.id, r.type, r.claim_number, r.text,
                 None if r.embedding is None else np.asarray(r.embedding, dtype=np.float32))
        for r in rows
    ]  # fmt: skip


def build_passages(
    patent_id: str, chunks: list[ChunkRow], embedder: Embedder, max_words: int
) -> tuple[list[Passage], np.ndarray]:
    """Cut chunks into passages of at most `max_words` words and embed them.

    A chunk that already fits reuses its stored embedding. Longer chunks (long claims) are cut
    at clause boundaries and the pieces are embedded here, which is cheap for a few references.
    """
    passages: list[Passage] = []
    vectors: list[np.ndarray | None] = []
    for chunk in chunks:
        for start, end in split_windows(chunk.text, max_words):
            whole = start == 0 and end == len(chunk.text.rstrip())
            passages.append(
                Passage(
                    chunk.id,
                    patent_id,
                    chunk.type,
                    chunk.claim_number,
                    chunk.text[start:end],
                    start,
                    end,
                )  # fmt: skip
            )
            vectors.append(chunk.embedding if whole else None)

    missing = [i for i, vec in enumerate(vectors) if vec is None]
    if missing:
        computed = embedder.encode_documents([passages[i].text for i in missing])
        for slot, vec in zip(missing, computed, strict=True):
            vectors[slot] = np.asarray(vec, dtype=np.float32)
    if not passages:
        return [], np.empty((0, 0), dtype=np.float32)
    return passages, np.vstack(vectors)


def select_for_elements(
    passages: list[Passage],
    matrix: np.ndarray,
    element_vectors: np.ndarray,
    per_element: int,
) -> list[list[Passage]]:
    """For every element, its `per_element` best passages with cosine scores, best first.

    Vectors are L2-normalized, so the dot product is the cosine similarity.
    """
    if not passages:
        return [[] for _ in range(len(element_vectors))]
    scores = matrix @ element_vectors.T  # passages x elements
    picked: list[list[Passage]] = []
    for column in range(scores.shape[1]):
        order = np.argsort(-scores[:, column], kind="stable")[:per_element]
        picked.append(
            [replace(passages[i], score=round(float(scores[i, column]), 4)) for i in order]
        )
    return picked
