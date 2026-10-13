from datetime import date

from support import FakeEmbedder, FakeReranker

from app.config import Settings
from app.search.schemas import DisclosureQuery
from app.search.service import SearchService, build_query_texts

BATTERY = DisclosureQuery(
    title="Battery thermal runaway early detection",
    summary=(
        "A battery management unit measures cell impedance and senses electrolyte gas in the "
        "pack housing to detect thermal runaway early and isolate the pack with a contactor."
    ),
    elements=[
        "impedance measurement of lithium ion cells",
        "gas sensor detecting electrolyte vapour in the pack housing",
        "contactor opened to isolate the battery pack",
    ],
    priority_date=date(2018, 1, 1),
)


def make_service(factory, reranker="default", **settings) -> SearchService:
    chosen = FakeReranker() if reranker == "default" else reranker
    return SearchService(factory, FakeEmbedder(), chosen, Settings(**settings))


def test_build_query_texts_labels_summary_title_and_elements():
    labelled = build_query_texts(BATTERY)
    assert [label for label, _ in labelled] == ["summary", "title", "E1", "E2", "E3"]
    empty = DisclosureQuery("", "  ", [""], date(2018, 1, 1))
    assert build_query_texts(empty) == []


def test_most_relevant_patent_ranks_first(seeded):
    response = make_service(seeded).search(BATTERY)
    assert response.hits[0].patent_id == "US100A1"
    assert response.hits[0].rerank_score is not None
    assert {"embed", "retrieve", "rerank", "total"} <= set(response.timings_ms)


def test_only_earlier_publications_are_returned(seeded):
    response = make_service(seeded).search(BATTERY)
    ids = {hit.patent_id for hit in response.hits}
    assert "US106A1" not in ids  # published 2019, after the priority date
    assert all(hit.publication_date < BATTERY.priority_date for hit in response.hits)

    earlier = DisclosureQuery(**{**BATTERY.__dict__, "priority_date": date(2016, 5, 1)})
    assert "US100A1" not in {h.patent_id for h in make_service(seeded).search(earlier).hits}


def test_matched_chunks_belong_to_the_patent_and_are_claims_or_abstracts(seeded):
    for hit in make_service(seeded).search(BATTERY).hits:
        assert hit.matched_chunks
        assert all(m.chunk_id.startswith(hit.patent_id + ":") for m in hit.matched_chunks)
        assert {m.chunk_type for m in hit.matched_chunks} <= {"claim", "abstract"}
        assert hit.matched_chunk_ids == [m.chunk_id for m in hit.matched_chunks]


def test_cpc_prefix_filter(seeded):
    query = DisclosureQuery(**{**BATTERY.__dict__, "cpc_prefix": "g06n"})
    ids = {hit.patent_id for hit in make_service(seeded).search(query).hits}
    assert ids and ids <= {"US101A1", "US9000001"}


def test_source_filter(seeded):
    query = DisclosureQuery(
        title="Neural network training with weight aggregation",
        summary="Training neural networks at several sites and aggregating model weights.",
        elements=["aggregation of model weights"],
        priority_date=date(2018, 1, 1),
        sources=("PV_GRANT",),
    )
    hits = make_service(seeded).search(query).hits
    assert [h.patent_id for h in hits] == ["US9000001"]
    assert hits[0].source == "PV_GRANT"


def test_without_reranker_results_use_fused_score(seeded):
    response = make_service(seeded, reranker=None).search(BATTERY)
    assert response.hits[0].patent_id == "US100A1"
    assert all(h.rerank_score is None and h.score == h.fused_score for h in response.hits)


def test_result_limit_and_rerank_depth_are_respected(seeded):
    response = make_service(seeded, result_limit=2, rerank_depth=3).search(BATTERY)
    assert len(response.hits) == 2


def test_cpc_suggestions_vote_over_top_results(seeded):
    response = make_service(seeded).search(BATTERY)
    subclasses = [s.subclass for s in response.suggested_cpc]
    assert "H01M" in subclasses and "B60L" in subclasses
    assert all(s.votes >= 1 for s in response.suggested_cpc)


def test_empty_query_and_no_matches_return_empty_responses(seeded):
    service = make_service(seeded)
    assert service.search(DisclosureQuery("", "", [], date(2018, 1, 1))).hits == []
    early = DisclosureQuery(**{**BATTERY.__dict__, "priority_date": date(2000, 1, 1)})
    assert service.search(early).hits == []


def test_vector_query_plan_can_use_the_hnsw_index(seeded):
    plan = make_service(seeded).explain_vector_query(BATTERY, disable_seqscan=True)
    assert "ix_patent_chunks_embedding_hnsw" in plan


def test_search_does_not_modify_the_corpus(seeded):
    service = make_service(seeded)
    service.search(BATTERY)
    with seeded() as session:
        from sqlalchemy import text

        assert session.execute(text("SELECT count(*) FROM patents")).scalar_one() == 8
