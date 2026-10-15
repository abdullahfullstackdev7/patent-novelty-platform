"""The evaluation tooling: search metrics, chart agreement and the threshold sweep."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.pipeline import evaluation as chart
from app.search import evaluation as search

S = Settings()


# ---- search metrics ---------------------------------------------------------------------------------


def test_patent_numbers_are_normalised_across_formats():
    for value in ("US 10,123,456 B2", "10123456", "US010123456", "us10123456b2"):
        assert search.normalize_patent_number(value) == "10123456"
    assert search.normalize_patent_number("") == ""


def test_recall_at_k_counts_the_share_of_cited_references_found():
    ranked = ["a", "b", "c", "d", "e"]
    assert search.recall_at_k(ranked, {"a", "e"}, 1) == 0.5
    assert search.recall_at_k(ranked, {"a", "e"}, 5) == 1.0
    assert search.recall_at_k(ranked, {"z"}, 5) == 0.0
    assert search.recall_at_k(ranked, set(), 5) == 0.0
    assert search.recall_at_k([], {"a"}, 10) == 0.0


def test_reciprocal_rank_uses_the_first_hit():
    assert search.reciprocal_rank(["x", "a", "b"], {"a", "b"}) == 0.5
    assert search.reciprocal_rank(["a"], {"a"}) == 1.0
    assert search.reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_evaluate_averages_over_queries_and_removes_the_query_patent_from_its_results():
    runs = {"p1": ["p1", "a", "b"], "p2": ["x", "y", "c"], "p3": []}

    summary = search.evaluate(
        [("p1", {"a"}), ("p2", {"c", "d"}), ("p3", {"e"})], lambda pid: runs[pid], ks=(1, 3)
    )
    # p1: "a" is rank 1 once the patent itself is removed. p2: one of two found by 3. p3: nothing returned.
    assert summary.queries == 3
    assert summary.recall[1] == pytest.approx((1.0 + 0.0 + 0.0) / 3)
    assert summary.recall[3] == pytest.approx((1.0 + 0.5 + 0.0) / 3)
    assert summary.mrr == pytest.approx((1.0 + 1 / 3 + 0.0) / 3)
    assert [r.relevant for r in summary.per_query] == [1, 2, 1]
    assert "recall@3 | 0.500 |" in summary.as_markdown()


def test_an_empty_evaluation_is_all_zeros():
    summary = search.evaluate([], lambda pid: [])
    assert summary.queries == 0 and summary.mrr == 0.0 and set(summary.recall.values()) == {0.0}


def test_only_examiner_citations_are_loaded(tmp_path):
    tsv = tmp_path / "citations.tsv"
    tsv.write_text(
        "patent_id\tcitation_patent_id\tcitation_category\n"
        "10000001\t9000001\tcited by examiner\n"
        "10000001\t9000002\tcited by applicant\n"
        "10000001\t9000003\tCited by Examiner\n"
        "10000002\t10000002\tcited by examiner\n"
        "\t9000009\tcited by examiner\n",
        encoding="utf-8",
    )
    assert search.load_examiner_citations(tsv) == {"10000001": {"9000001", "9000003"}}


def test_cases_are_limited_to_cited_references_that_are_in_the_corpus():
    corpus = {"US1": "1", "US2": "2", "US3": "3", "US4": "4"}
    citations = {"1": {"2", "99"}, "2": {"99"}, "3": {"1", "2"}, "4": set()}
    assert search.pick_cases(corpus, citations, 10) == [("US1", {"US2"}), ("US3", {"US1", "US2"})]
    assert search.pick_cases(corpus, citations, 1) == [("US1", {"US2"})]


# ---- chart agreement ---------------------------------------------------------------------------------


def pair(human, cosine, overlap=0.8, llm=None):
    return chart.LabelledPair("an element", "a passage", human, cosine, overlap, llm)


def test_accuracy_and_kappa():
    gold = ["disclosed", "partial", "not_found", "not_found"]
    assert chart.accuracy(gold, gold) == 1.0
    assert chart.cohen_kappa(gold, gold) == 1.0
    assert chart.accuracy(["partial"] * 4, gold) == 0.25
    assert chart.cohen_kappa(["not_found"] * 4, gold) == 0.0  # always guessing the commonest label is chance level
    assert chart.accuracy([], []) == 0.0 and chart.cohen_kappa([], []) == 0.0


def test_confusion_table_counts_each_pair_once():
    table = chart.confusion(["disclosed", "partial", "partial"], ["disclosed", "disclosed", "partial"])
    assert table["disclosed"] == {"disclosed": 1, "partial": 1, "not_found": 0}
    assert table["partial"]["partial"] == 1
    assert sum(sum(row.values()) for row in table.values()) == 3


def test_final_verdict_mirrors_the_pipeline():
    assert chart.final_verdict(pair("not_found", 0.2), S) == ("not_found", False)
    assert chart.final_verdict(pair("disclosed", 0.95, overlap=0.9), S) == ("disclosed", False)
    assert chart.final_verdict(pair("partial", 0.6, llm="partial"), S) == ("partial", True)
    assert chart.final_verdict(pair("partial", 0.7), S) == ("partial", True)  # no model verdict: the local fallback
    assert chart.final_verdict(pair("not_found", 0.5), S) == ("not_found", True)
    assert chart.final_verdict(pair("partial", 0.95, overlap=0.1, llm="partial"), S) == ("partial", True)  # high score, low overlap


def test_agreement_report_separates_local_and_model_cells():
    pairs = [pair("not_found", 0.1), pair("disclosed", 0.95, 0.9), pair("partial", 0.6, llm="partial"), pair("disclosed", 0.6, llm="partial")]
    report = chart.agreement_report(pairs, S)
    assert report["pairs"] == 4 and report["local_cells"] == 2 and report["llm_cells"] == 2
    assert report["local_accuracy"] == 1.0 and report["llm_accuracy"] == 0.5
    assert report["overall_accuracy"] == 0.75


def test_sweep_ranks_thresholds_by_agreement_then_by_model_use():
    pairs = [pair("not_found", 0.38, llm="partial"), pair("not_found", 0.40, llm="partial"), pair("partial", 0.6, llm="partial"), pair("disclosed", 0.9, 0.9), pair("not_found", 0.2)]
    rows = chart.sweep_thresholds(pairs, S)
    best = rows[0]
    assert best.accuracy == max(r.accuracy for r in rows)
    assert (best.low, best.accuracy) == (0.45, 1.0)  # the model is wrong on the 0.38 and 0.40 pairs, so they must stay local
    assert all(r.low < r.high for r in rows)
    same_accuracy = [r for r in rows if r.accuracy == best.accuracy]
    assert same_accuracy == sorted(same_accuracy, key=lambda r: (r.llm_share, r.low, r.high))


def test_label_files_are_validated(tmp_path):
    path = tmp_path / "labels.csv"
    chart.write_template(path)
    assert chart.load_labels(path) == []
    path.write_text(
        ",".join(chart.COLUMNS) + "\nE1,text,disclosed,0.9,0.8,\nE2,text,,0.5,0.5,\nE3,text,partial,0.6,0.4,partial\n", encoding="utf-8"
    )
    rows = chart.load_labels(path)
    assert [r.human for r in rows] == ["disclosed", "partial"]  # the unlabelled row is skipped
    assert rows[1].llm == "partial" and rows[0].llm is None
    path.write_text(",".join(chart.COLUMNS) + "\nE1,text,maybe,0.9,0.8,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="human_status"):
        chart.load_labels(path)
    path.write_text(",".join(chart.COLUMNS) + "\nE1,text,partial,0.9,0.8,perhaps\n", encoding="utf-8")
    with pytest.raises(ValueError, match="llm_status"):
        chart.load_labels(path)
