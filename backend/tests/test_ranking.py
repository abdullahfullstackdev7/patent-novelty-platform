from app.search import ranking


def test_extract_keywords_drops_stopwords_and_orders_by_frequency():
    text = "battery battery impedance sensor the sensor battery with using"
    assert ranking.extract_keywords(text, limit=3) == ["battery", "sensor", "impedance"]


def test_extract_keywords_is_deterministic_on_ties():
    assert ranking.extract_keywords("zebra apple mangoes", limit=3) == ["mangoes", "apple", "zebra"]


def test_build_or_query_joins_terms_with_or_and_handles_empty():
    assert ranking.build_or_query("battery sensor battery", limit=5) == "battery or sensor"
    assert ranking.build_or_query("the and of") == ""


def test_rrf_fuse_sums_reciprocal_ranks_and_ignores_duplicates():
    scores = ranking.rrf_fuse([["a", "b", "a"], ["b", "c"]], k=60)
    assert scores["a"] == 1 / 61
    assert scores["b"] == 1 / 62 + 1 / 61
    assert scores["c"] == 1 / 62
    assert max(scores, key=scores.get) == "b"


def test_aggregate_by_patent_uses_max_plus_mean_of_top_three():
    chunk_scores = {"p1:a": 0.4, "p1:b": 0.2, "p1:c": 0.1, "p1:d": 0.05, "p2:a": 0.5}
    chunk_patent = {"p1:a": "p1", "p1:b": "p1", "p1:c": "p1", "p1:d": "p1", "p2:a": "p2"}
    result = ranking.aggregate_by_patent(chunk_scores, chunk_patent)
    by_id = {r.patent_id: r for r in result}
    assert by_id["p1"].score == 0.4 + (0.4 + 0.2 + 0.1) / 3
    assert by_id["p1"].chunk_ids == ["p1:a", "p1:b", "p1:c"]
    assert by_id["p2"].score == 0.5 + 0.5
    assert [r.patent_id for r in result] == ["p2", "p1"]


def test_vote_cpc_counts_each_patent_once_and_breaks_ties_by_rank():
    ranked = [["G06N", "G06N", "G06F"], ["G06F"], ["H04L", "G06N"], ["H04L"]]
    # G06F and G06N first appear in the same patent, so the name decides; H04L appears later
    assert ranking.vote_cpc(ranked, depth=10, top=3) == [("G06F", 2), ("G06N", 2), ("H04L", 2)]
    assert ranking.vote_cpc(ranked, depth=1, top=5) == [("G06F", 1), ("G06N", 1)]


def test_like_prefix_escapes_wildcards():
    assert ranking.like_prefix(" g06n3 ") == "G06N3%"
    assert ranking.like_prefix("a%b_c") == "A\\%B\\_C%"
