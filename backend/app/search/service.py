"""Hybrid search: local embeddings + full text, reciprocal rank fusion, cross-encoder rerank."""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import date

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.search import ranking
from app.search.embedding import Embedder, Reranker
from app.search.schemas import (
    ChunkMatch,
    CpcSuggestion,
    DisclosureQuery,
    SearchHit,
    SearchResponse,
)

RETRIEVAL_TYPES = ("claim", "abstract")
RERANK_QUERY_WORDS = 200
RERANK_ABSTRACT_WORDS = 150
RERANK_CHUNK_WORDS = 100


def vector_literal(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vector) + "]"


def _truncate_words(value: str, limit: int) -> str:
    words = value.split()
    return value if len(words) <= limit else " ".join(words[:limit])


def build_query_texts(query: DisclosureQuery) -> list[tuple[str, str]]:
    """Whole-disclosure summary, title and each element, empty strings removed."""
    labelled = [("summary", query.summary), ("title", query.title)]
    labelled += [(f"E{i}", element) for i, element in enumerate(query.elements, start=1)]
    return [(label, value.strip()) for label, value in labelled if value and value.strip()]


def _filters(query: DisclosureQuery) -> tuple[str, dict[str, object]]:
    clauses = ["c.publication_date < :priority_date", "c.type = ANY(:types)"]
    params: dict[str, object] = {
        "priority_date": query.priority_date,
        "types": list(RETRIEVAL_TYPES),
    }
    if query.sources:
        clauses.append("c.source = ANY(:sources)")
        params["sources"] = list(query.sources)
    if query.cpc_prefix:
        clauses.append(
            "EXISTS (SELECT 1 FROM patents p WHERE p.id = c.patent_id AND EXISTS ("
            "SELECT 1 FROM unnest(p.cpc_codes) AS code WHERE code LIKE :cpc_like ESCAPE '\\'))"
        )
        params["cpc_like"] = ranking.like_prefix(query.cpc_prefix)
    return " AND ".join(clauses), params


VECTOR_SQL = """
SELECT c.id
FROM patent_chunks c
WHERE {where}
ORDER BY c.embedding <=> CAST(:qvec AS vector)
LIMIT :n
"""

FTS_SQL = """
SELECT c.id
FROM patent_chunks c, websearch_to_tsquery('english', :qtext) AS q(query)
WHERE c.tsv @@ q.query AND {where}
ORDER BY ts_rank_cd(c.tsv, q.query) DESC, c.id
LIMIT :n
"""


class SearchService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedder: Embedder,
        reranker: Reranker | None,
        settings: Settings | None = None,
    ) -> None:
        self._sessions = session_factory
        self._embedder = embedder
        self._reranker = reranker
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------ retrieval

    def _retrieve(
        self, session: Session, query: DisclosureQuery, texts: Sequence[str], vectors: np.ndarray
    ) -> list[list[str]]:
        where, params = _filters(query)
        limit = self._settings.search_candidates_per_query
        # HNSW is approximate. Iterative scans keep scanning until the filtered LIMIT is met.
        session.execute(text(f"SET LOCAL hnsw.ef_search = {int(self._settings.hnsw_ef_search)}"))
        session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        rankings: list[list[str]] = []
        vector_sql = text(VECTOR_SQL.format(where=where))
        for vector in vectors:
            rows = session.execute(
                vector_sql, {**params, "qvec": vector_literal(vector), "n": limit}
            )
            rankings.append([row[0] for row in rows])
        fts_sql = text(FTS_SQL.format(where=where))
        for value in texts:
            expression = ranking.build_or_query(value)
            if not expression:
                continue
            rows = session.execute(fts_sql, {**params, "qtext": expression, "n": limit})
            rankings.append([row[0] for row in rows])
        return rankings

    def explain_vector_query(self, query: DisclosureQuery, *, disable_seqscan: bool = False) -> str:
        """EXPLAIN plan text for the vector query of the disclosure summary.

        With `disable_seqscan`, sequential scans, bitmap scans and sorts are turned off.
        """
        vector = self._embedder.encode_queries([query.summary or query.title])[0]
        where, params = _filters(query)
        with self._sessions() as session:
            session.execute(
                text(f"SET LOCAL hnsw.ef_search = {int(self._settings.hnsw_ef_search)}")
            )
            session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            if disable_seqscan:
                # Only the HNSW index can return rows ordered by distance without a sort, so
                # this shows whether the index is usable even on a table too small to need it.
                for setting in ("enable_seqscan", "enable_bitmapscan", "enable_sort"):
                    session.execute(text(f"SET LOCAL {setting} = off"))
            rows = session.execute(
                text("EXPLAIN " + VECTOR_SQL.format(where=where)),
                {
                    **params,
                    "qvec": vector_literal(vector),
                    "n": self._settings.search_candidates_per_query,
                },
            )
            plan = "\n".join(row[0] for row in rows)
            session.rollback()
        return plan

    # ------------------------------------------------------------------ main entry

    def search(self, query: DisclosureQuery) -> SearchResponse:
        settings = self._settings
        started = time.perf_counter()
        labelled = build_query_texts(query)
        if not labelled:
            return SearchResponse([], [], {"total": 0.0})
        texts = [value for _, value in labelled]

        mark = time.perf_counter()
        vectors = self._embedder.encode_queries(texts)
        timings = {"embed": (time.perf_counter() - mark) * 1000}

        with self._sessions() as session:
            mark = time.perf_counter()
            rankings = self._retrieve(session, query, texts, vectors)
            chunk_scores = ranking.rrf_fuse(rankings, settings.rrf_k)
            if not chunk_scores:
                session.rollback()
                timings["retrieve"] = (time.perf_counter() - mark) * 1000
                timings["total"] = (time.perf_counter() - started) * 1000
                return SearchResponse([], [], timings)

            chunk_rows = session.execute(
                text(
                    "SELECT id, patent_id, type, claim_number, text FROM patent_chunks "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": list(chunk_scores)},
            ).all()
            chunk_info = {row.id: row for row in chunk_rows}
            chunk_patent = {chunk_id: row.patent_id for chunk_id, row in chunk_info.items()}
            fused = ranking.aggregate_by_patent(
                {cid: s for cid, s in chunk_scores.items() if cid in chunk_patent}, chunk_patent
            )

            candidates = fused[: settings.rerank_depth]
            patent_rows = session.execute(
                text(
                    "SELECT id, title, abstract, source, assignee, publication_date, "
                    "cpc_subclasses, url FROM patents WHERE id = ANY(:ids)"
                ),
                {"ids": [c.patent_id for c in candidates]},
            ).all()
            patents = {row.id: row for row in patent_rows}

            # CPC suggestions vote over the best fused patents, before reranking.
            vote_ids = [c.patent_id for c in fused[: settings.cpc_vote_depth]]
            missing = [pid for pid in vote_ids if pid not in patents]
            if missing:
                extra = session.execute(
                    text("SELECT id, cpc_subclasses FROM patents WHERE id = ANY(:ids)"),
                    {"ids": missing},
                ).all()
                subclasses = {row.id: row.cpc_subclasses for row in extra}
            else:
                subclasses = {}
            subclasses.update({pid: row.cpc_subclasses for pid, row in patents.items()})
            suggested = [
                CpcSuggestion(subclass, votes)
                for subclass, votes in ranking.vote_cpc(
                    [subclasses.get(pid, []) for pid in vote_ids], settings.cpc_vote_depth
                )
            ]
            session.rollback()  # read-only work, nothing to commit
            timings["retrieve"] = (time.perf_counter() - mark) * 1000

        mark = time.perf_counter()
        rerank_scores = self._rerank(query, candidates, patents, chunk_info)
        timings["rerank"] = (time.perf_counter() - mark) * 1000

        hits: list[SearchHit] = []
        for candidate, rerank_score in zip(candidates, rerank_scores, strict=True):
            row = patents.get(candidate.patent_id)
            if row is None:
                continue
            matches = [
                ChunkMatch(
                    chunk_id=cid,
                    chunk_type=chunk_info[cid].type,
                    claim_number=chunk_info[cid].claim_number,
                    text=chunk_info[cid].text,
                    score=chunk_scores[cid],
                )
                for cid in candidate.chunk_ids
            ]
            hits.append(
                SearchHit(
                    patent_id=row.id,
                    title=row.title,
                    source=row.source,
                    assignee=row.assignee,
                    publication_date=row.publication_date,
                    cpc_subclasses=list(row.cpc_subclasses),
                    url=row.url,
                    score=rerank_score if rerank_score is not None else candidate.score,
                    fused_score=candidate.score,
                    rerank_score=rerank_score,
                    matched_chunks=matches,
                )
            )
        hits.sort(key=lambda h: (-h.score, h.patent_id))
        timings["total"] = (time.perf_counter() - started) * 1000
        return SearchResponse(hits[: settings.result_limit], suggested, timings)

    def _rerank(
        self,
        query: DisclosureQuery,
        candidates: Sequence[ranking.PatentScore],
        patents: dict[str, object],
        chunk_info: dict[str, object],
    ) -> list[float | None]:
        if self._reranker is None:
            return [None] * len(candidates)
        question = _truncate_words(f"{query.title}. {query.summary}", RERANK_QUERY_WORDS)
        documents: list[str] = []
        for candidate in candidates:
            row = patents.get(candidate.patent_id)
            if row is None:
                documents.append("")
                continue
            best = chunk_info[candidate.chunk_ids[0]].text
            documents.append(
                f"{row.title}. "
                f"{_truncate_words(row.abstract, RERANK_ABSTRACT_WORDS)} "
                f"{_truncate_words(best, RERANK_CHUNK_WORDS)}"
            )
        return list(self._reranker.score(question, documents))


def priority_date_from(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)
