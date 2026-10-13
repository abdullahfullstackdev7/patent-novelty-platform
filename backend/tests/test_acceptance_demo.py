"""Phase 2 acceptance on the real demo corpus with the real models.

Needs the dev database loaded by `scripts/quickstart_demo.py`, so it is skipped otherwise:
  - the 8 sample disclosures all return results,
  - p95 search latency stays under 2 seconds,
  - EXPLAIN shows the HNSW index being used.
"""

from __future__ import annotations

import os
import statistics
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.search.cli import load_disclosure
from app.search.embedding import CrossEncoderReranker, SentenceTransformerEmbedder
from app.search.service import SearchService

pytestmark = pytest.mark.demo

DEV_URL = os.environ.get(
    "DEV_DATABASE_URL", "postgresql+psycopg://priorart:priorart@localhost:54329/priorart"
)
DISCLOSURES = sorted(
    (Path(__file__).resolve().parents[2] / "dataset" / "disclosures").glob("*.json")
)
REPEATS = 3
P95_LIMIT_SECONDS = 2.0


@pytest.fixture(scope="module")
def service():
    engine = create_engine(DEV_URL)
    try:
        with engine.connect() as conn:
            embedded = conn.execute(
                text("SELECT count(*) FROM patent_chunks WHERE embedding IS NOT NULL")
            ).scalar_one()
    except Exception as error:  # database down or schema missing
        pytest.skip(f"dev database not available: {error}")
    if embedded < 1000:
        pytest.skip("demo corpus not loaded, run scripts/quickstart_demo.py")
    settings = Settings(database_url=DEV_URL)
    yield SearchService(
        sessionmaker(engine, expire_on_commit=False),
        SentenceTransformerEmbedder(settings),
        CrossEncoderReranker(settings),
        settings,
    )
    engine.dispose()


def test_eight_sample_disclosures_exist():
    assert len(DISCLOSURES) == 8


def test_every_sample_disclosure_returns_results_and_p95_is_under_two_seconds(service):
    queries = [load_disclosure(path) for path in DISCLOSURES]
    service.search(queries[0])  # warm up models and caches
    latencies: list[float] = []
    for query in queries:
        for _ in range(REPEATS):
            response = service.search(query)
            latencies.append(response.timings_ms["total"] / 1000)
            assert response.hits, f"no results for {query.title}"
            assert response.suggested_cpc
            assert all(h.publication_date < query.priority_date for h in response.hits)
    p95 = statistics.quantiles(latencies, n=20)[18]
    print(
        f"\nlatency over {len(latencies)} searches: median {statistics.median(latencies):.2f}s, "
        f"p95 {p95:.2f}s, max {max(latencies):.2f}s"
    )
    assert p95 < P95_LIMIT_SECONDS


def test_explain_shows_the_hnsw_index(service):
    query = load_disclosure(DISCLOSURES[0])
    forced = service.explain_vector_query(query, disable_seqscan=True)
    print("\n" + forced)
    assert "ix_patent_chunks_embedding_hnsw" in forced
