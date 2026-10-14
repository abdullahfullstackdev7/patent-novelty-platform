"""Pipeline building blocks without a database."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from pipeline_support import chart_items
from support import FakeEmbedder

from app.config import Settings
from app.llm import prompts
from app.llm.budget import estimate_tokens
from app.llm.errors import AllProvidersUnavailable, InvalidOutput, LocalOnly, PromptTooLarge
from app.llm.prompts.models import ChartCellItem, ChartOut
from app.pipeline import classify, intake, risk
from app.pipeline.charting import _batches, cell_input_hash, chart_reference
from app.pipeline.passages import ChunkRow, Passage, build_passages, select_for_elements
from app.pipeline.risk import RefCells, assess
from app.pipeline.textsplit import sentence_spans, split_windows
from app.services import export
from app.services.reports import DISCLAIMER, drafting_considerations, template_summary

S = Settings(jwt_secret="x" * 40, fernet_key="x")


# ---- text spans ------------------------------------------------------------------


def test_windows_are_exact_substrings_within_the_word_limit():
    text = " ".join(f"word{i}" + ("." if i % 17 == 16 else "") for i in range(400))
    spans = split_windows(text, 120)
    assert len(spans) >= 4
    covered = []
    for start, end in spans:
        piece = text[start:end]
        assert len(piece.split()) <= 120 and piece == piece.strip()
        covered.extend(piece.split())
    assert covered == text.split()  # nothing lost, nothing repeated


def test_windows_prefer_sentence_ends_and_handle_short_or_empty_text():
    text = ("alpha " * 100).strip() + ". " + ("beta " * 100).strip()
    first = text[: split_windows(text, 120)[0][1]]
    assert first.endswith("alpha.")  # cut at the sentence end, not mid-run
    assert split_windows("short text", 120) == [(0, 10)]
    assert split_windows("   ", 120) == []


def test_sentence_spans():
    text = "First one. Second; third: fourth!  Last"
    parts = [text[s:e] for s, e in sentence_spans(text)]
    assert parts == ["First one.", "Second;", "third:", "fourth!", "Last"]


# ---- classification ---------------------------------------------------------------


def test_keyword_overlap_uses_stemmed_content_words():
    assert (
        classify.keyword_overlap(
            "impedance measurement circuits", "an impedance measurement circuit"
        )
        == 1.0
    )
    assert classify.keyword_overlap("gas sensor", "nothing in common here") == 0.0
    assert classify.keyword_overlap("the of and", "anything") == 0.0  # no content words
    assert 0.3 < classify.keyword_overlap("gas sensor housing vapour", "a gas sensor") < 0.8


@pytest.mark.parametrize(
    ("score", "overlap", "expected"),
    [
        (0.0, 1.0, "not_found"),
        (0.349, 1.0, "not_found"),
        (0.35, 0.0, None),  # exactly on the low threshold is ambiguous
        (0.60, 1.0, None),
        (0.88, 1.0, None),  # must be strictly above the high threshold
        (0.881, 0.6, "disclosed"),
        (0.95, 0.59, None),  # high similarity but few shared words still needs the LLM
        (0.99, 1.0, "disclosed"),
    ],
)
def test_pre_classify_thresholds(score, overlap, expected):
    assert classify.pre_classify(score, overlap, S) == expected


def test_thresholds_follow_settings():
    strict = Settings(jwt_secret="x" * 40, fernet_key="x", pipeline_low_threshold=0.5)
    assert classify.pre_classify(0.45, 1.0, strict) == "not_found"
    assert classify.pre_classify(0.45, 1.0, S) is None


def test_local_fallback_and_downgrade():
    assert classify.local_fallback(0.65, S) == "partial"
    assert classify.local_fallback(0.64, S) == "not_found"
    assert classify.downgrade("disclosed") == "partial"
    assert (
        classify.downgrade("partial") == "partial"
        and classify.downgrade("not_found") == "not_found"
    )


def test_confidence_is_bounded_and_moves_the_right_way():
    for status in ("disclosed", "partial", "not_found"):
        for score in np.linspace(0, 1, 21):
            assert 0 <= classify.confidence(status, float(score), S) <= 1
    assert classify.confidence("disclosed", 0.95, S) > classify.confidence("disclosed", 0.5, S)
    assert classify.confidence("not_found", 0.0, S) > classify.confidence("not_found", 0.34, S)
    assert classify.confidence("disclosed", 0.95, S) > classify.confidence("partial", 0.95, S)


def test_best_excerpt_is_a_verbatim_substring_with_correct_offsets():
    passage = (
        "The housing holds the cells. A gas sensor detects electrolyte vapour in the housing. "
        "The pack is mounted on a frame."
    )
    excerpt, start, end = classify.best_excerpt(passage, "gas sensor for electrolyte vapour")
    assert excerpt == "A gas sensor detects electrolyte vapour in the housing."
    assert passage[start:end] == excerpt
    long_sentence = "alpha " * 100
    clipped, s, e = classify.best_excerpt(long_sentence.strip(), "alpha")
    assert len(clipped.split()) == classify.EXCERPT_WORDS and long_sentence.strip()[s:e] == clipped


def test_excerpt_verification_rejects_anything_not_in_the_source():
    source = "The unit measures impedance. A contactor opens."
    assert classify.excerpt_is_verbatim("A contactor opens.", source, 29, 47)
    assert not classify.excerpt_is_verbatim("A contactor closes.", source, 29, 47)  # altered
    assert not classify.excerpt_is_verbatim("A contactor opens.", source, 0, 18)  # wrong offsets
    assert not classify.excerpt_is_verbatim("", source, 0, 0)
    assert not classify.excerpt_is_verbatim(None, source, None, None)
    assert not classify.excerpt_is_verbatim("x", source, 0, 999)


# ---- passages ----------------------------------------------------------------------


class CountingEmbedder(FakeEmbedder):
    def __init__(self):
        self.embedded: list[str] = []

    def encode_documents(self, texts):
        self.embedded.extend(texts)
        return super().encode_documents(texts)


def test_passages_reuse_stored_embeddings_and_embed_only_long_chunks():
    embedder = CountingEmbedder()
    short_text = "A gas sensor detects vapour in the housing."
    long_text = " ".join(
        f"clause{i} of the long claim" + ("," if i % 9 == 8 else "") for i in range(120)
    )
    stored = FakeEmbedder().encode_documents([short_text])[0]
    rows = [
        ChunkRow("P:claim:1", "claim", 1, short_text, stored),
        ChunkRow("P:claim:2", "claim", 2, long_text, None),
    ]
    passages, matrix = build_passages("P", rows, embedder, max_words=120)

    assert len(passages) >= 3 and matrix.shape == (len(passages), stored.shape[0])
    assert short_text not in embedder.embedded  # stored vector was reused
    for p in passages:
        assert len(p.text.split()) <= 120
        source = short_text if p.chunk_id == "P:claim:1" else long_text
        assert source[p.char_start : p.char_end] == p.text


def test_select_for_elements_returns_best_two_with_scores():
    embedder = FakeEmbedder()
    texts = ["impedance measurement circuit", "gas sensor for vapour", "frame bracket mount"]
    rows = [ChunkRow(f"P:claim:{i}", "claim", i, t, v) for i, (t, v) in
            enumerate(zip(texts, embedder.encode_documents(texts), strict=True), start=1)]  # fmt: skip
    passages, matrix = build_passages("P", rows, embedder, 120)
    vectors = embedder.encode_queries(["gas sensor vapour", "impedance circuit"])
    picked = select_for_elements(passages, matrix, vectors, per_element=2)
    assert [p.chunk_id for p in picked[0]][0] == "P:claim:2"
    assert [p.chunk_id for p in picked[1]][0] == "P:claim:1"
    assert all(len(group) == 2 for group in picked)
    assert picked[0][0].score >= picked[0][1].score > -1
    assert select_for_elements([], np.empty((0, 0)), vectors, 2) == [[], []]


# ---- risk logic ---------------------------------------------------------------------


def ref(pid, statuses, subclasses=("G06N",), conf=0.9):
    keys = [f"E{i}" for i in range(1, len(statuses) + 1)]
    return RefCells(
        pid, subclasses, dict(zip(keys, statuses, strict=True)), {k: conf for k in keys}
    )


KEYS = ["E1", "E2", "E3", "E4", "E5"]
D, P, N = "disclosed", "partial", "not_found"


def test_one_reference_with_everything_is_anticipation_high():
    result = assess(KEYS, [ref("A", [D] * 5), ref("B", [N] * 5)])
    assert result.level == "high" and result.anticipation_reference == "A"
    assert 85 <= result.score <= 100 and result.uncovered_elements == []
    assert "anticipation" in result.basis


def test_combination_in_the_same_cpc_subclass_is_medium_high():
    a = ref("A", [D, D, D, N, N], ("G06N", "G06F"))
    b = ref("B", [N, N, N, D, D], ("G06N",))
    result = assess(KEYS, [a, b])
    assert result.level == "medium_high" and result.combination == ["A", "B"]
    assert result.shared_subclasses == ["G06N"] and 65 <= result.score <= 84


def test_combination_across_different_subclasses_is_medium():
    a = ref("A", [D, D, D, N, N], ("G06N",))
    b = ref("B", [N, N, N, D, D], ("H04L",))
    result = assess(KEYS, [a, b])
    assert result.level == "medium" and result.shared_subclasses == []
    assert 36 <= result.score <= 64 and "different CPC" in result.basis


def test_three_references_can_complete_the_picture_and_the_best_combination_wins():
    a = ref("A", [D, D, N, N, N], ("G06N",))
    b = ref("B", [N, N, D, N, N], ("H04L",))
    c = ref("C", [N, N, N, D, D], ("G06N",))
    result = assess(KEYS, [a, b, c])
    assert result.level == "medium" and result.combination == ["A", "B", "C"]
    shared = assess(KEYS, [a, ref("B2", [N, N, D, D, D], ("G06N",)), c])
    assert shared.level == "medium_high" and shared.combination == ["A", "B2"]  # smaller wins


def test_single_reference_at_80_percent_with_the_rest_partial_is_medium_high():
    result = assess(KEYS, [ref("A", [D, D, D, D, P], ("G06N",))])
    assert result.level == "medium_high" and result.combination == ["A"]
    not_partial = assess(KEYS, [ref("A", [D, D, D, D, N], ("G06N",))])
    assert not_partial.level == "low"  # the remaining element is not even partly disclosed


def test_low_risk_lists_the_points_of_novelty_and_the_per_element_table():
    a = ref("A", [D, P, N, N, N])
    b = ref("B", [N, P, N, D, N])
    result = assess(KEYS, [a, b])
    assert result.level == "low" and 0 <= result.score <= 35
    assert result.uncovered_elements == ["E2", "E3", "E5"]
    table = {row.element: row for row in result.per_element}
    assert table["E1"].disclosed_by == ["A"] and table["E2"].partial_in == ["A", "B"]
    assert table["E3"].novel and table["E2"].novel and not table["E1"].novel
    assert result.coverage["A"] == {"disclosed": 1, "partial": 1, "not_found": 3}
    assert "E2, E3, E5" in result.basis


def test_scores_stay_inside_their_band_and_levels_are_ordered():
    bands = {"low": (0, 35), "medium": (36, 64), "medium_high": (65, 84), "high": (85, 100)}
    cases = [
        [ref("A", [D] * 5)],
        [ref("A", [D, D, D, D, P])],
        [ref("A", [D, D, D, N, N]), ref("B", [N, N, N, D, D], ("H04L",))],
        [ref("A", [N] * 5)],
    ]
    seen = []
    for refs in cases:
        result = assess(KEYS, refs)
        low, high = bands[result.level]
        assert low <= result.score <= high
        seen.append(result.score)
    assert seen == sorted(seen, reverse=True)  # high > medium_high > medium > low


def test_confidence_changes_the_score_inside_a_band_but_not_the_level():
    strong = assess(KEYS, [ref("A", [D] * 5, conf=1.0)])
    weak = assess(KEYS, [ref("A", [D] * 5, conf=0.6)])
    assert strong.level == weak.level == "high" and strong.score > weak.score


def test_risk_is_deterministic_and_handles_empty_inputs():
    refs = [ref("A", [D, D, D, N, N]), ref("B", [N, N, N, D, D])]
    assert assess(KEYS, refs) == assess(KEYS, refs)
    empty = assess(KEYS, [])
    assert empty.level == "low" and empty.score == 0 and "No charted reference" in empty.basis
    assert assess([], refs).level == "low"
    assert risk.LABELS["medium_high"] == "Medium-High"


# ---- charting with a stub gateway -----------------------------------------------------


class StubGateway:
    """Returns scripted ChartOut values and counts calls. Behaves like LLMGateway.run."""

    def __init__(self, cells=None, raises=None, tokens=500):
        self.cells = cells
        self.raises = raises
        self.tokens = tokens
        self.requests: list[str] = []

    def run(self, spec, user, *, case_id=None, case_mode="auto"):
        self.requests.append(user)
        if self.raises:
            raise self.raises
        wanted = [item["e"] for item in chart_items(user)]
        cells = self.cells(wanted, chart_items(user)) if callable(self.cells) else self.cells
        return SimpleNamespace(
            value=ChartOut(cells=cells), total_tokens=self.tokens, calls=[object()],
            cache_hit=False, provider="stub",
        )  # fmt: skip


def passage(score, text="A gas sensor detects electrolyte vapour.", cid="US1:claim:1"):
    return Passage(cid, "US1", "claim", 1, text, 0, len(text), score)


ELEMS = {"E1": "gas sensor for electrolyte vapour", "E2": "contactor isolating the pack",
         "E3": "unrelated feature of another kind"}  # fmt: skip


def picks_for(scores):
    return {
        key: [passage(score), passage(score - 0.1, "Another sentence entirely.", "US1:abstract:0")]
        for key, score in zip(ELEMS, scores, strict=True)
    }


def test_clear_cases_are_decided_locally_without_any_llm_call():
    gateway = StubGateway()
    drafts, stats = chart_reference(gateway, "US1", {"E1": ELEMS["E1"], "E3": ELEMS["E3"]},
                                    {"E1": [passage(0.95)], "E3": [passage(0.10)]}, S)  # fmt: skip
    assert gateway.requests == [] and stats.llm_calls == 0 and stats.local_cells == 2
    assert drafts["E1"].status == "disclosed" and drafts["E1"].method == "local"
    assert drafts["E3"].status == "not_found" and drafts["E3"].method == "local"
    assert drafts["E1"].excerpt and drafts["E1"].char_start is not None
    assert drafts["E1"].rationale is None


def test_ambiguous_elements_go_to_the_llm_in_one_batched_call():
    cells = [
        ChartCellItem(e="E2", s="d", p="E2.1", r="x"),
        ChartCellItem(e="E3", s="n", p="", r="y"),
    ]
    gateway = StubGateway(cells)
    picks = {"E2": [passage(0.6)], "E3": [passage(0.5, "Other text here.", "US1:claim:2")]}
    drafts, stats = chart_reference(
        gateway, "US1", {"E2": ELEMS["E2"], "E3": ELEMS["E3"]}, picks, S
    )
    assert len(gateway.requests) == 1 and stats.llm_calls == 1 and stats.tokens == 500
    assert drafts["E2"].status == "disclosed" and drafts["E2"].method == "llm"
    assert drafts["E3"].status == "not_found" and drafts["E3"].method == "llm"
    assert drafts["E2"].rationale == "x" and stats.llm_used and stats.llm_cells == 2
    sent = chart_items(gateway.requests[0])
    assert [i["e"] for i in sent] == ["E2", "E3"] and all(len(i["ps"]) <= 2 for i in sent)


def test_a_citation_the_model_was_not_given_is_downgraded():
    gateway = StubGateway([ChartCellItem(e="E2", s="d", p="BOGUS", r="made up")])
    drafts, stats = chart_reference(gateway, "US1", {"E2": ELEMS["E2"]}, {"E2": [passage(0.7)]}, S)
    assert drafts["E2"].status == "partial" and stats.downgraded == 1
    assert drafts["E2"].confidence < classify.confidence("partial", 0.7, S)  # penalised
    untouched = StubGateway([ChartCellItem(e="E2", s="n", p="", r="no")])
    drafts, stats = chart_reference(
        untouched, "US1", {"E2": ELEMS["E2"]}, {"E2": [passage(0.7)]}, S
    )
    assert drafts["E2"].status == "not_found" and stats.downgraded == 0  # n needs no citation


def test_elements_the_model_skipped_fall_back_to_local_rules():
    gateway = StubGateway([ChartCellItem(e="E2", s="p", p="E2.1", r="ok")])
    picks = {"E2": [passage(0.6)], "E3": [passage(0.70)]}
    drafts, stats = chart_reference(
        gateway, "US1", {"E2": ELEMS["E2"], "E3": ELEMS["E3"]}, picks, S
    )
    assert drafts["E2"].method == "llm"
    assert drafts["E3"].method == "local" and drafts["E3"].status == "partial"  # 0.70 >= 0.65
    assert stats.fallback_cells == 1


@pytest.mark.parametrize(
    ("failure", "label"),
    [(LocalOnly("off"), "local_only"), (AllProvidersUnavailable("down"), "AllProvidersUnavailable"),
     (PromptTooLarge("big"), "PromptTooLarge"), (InvalidOutput("bad"), "InvalidOutput")],
)  # fmt: skip
def test_when_the_llm_cannot_answer_every_cell_still_gets_a_local_verdict(failure, label):
    gateway = StubGateway(raises=failure)
    picks = {"E2": [passage(0.60)], "E3": [passage(0.70)]}
    drafts, stats = chart_reference(
        gateway, "US1", {"E2": ELEMS["E2"], "E3": ELEMS["E3"]}, picks, S
    )
    assert stats.error == label and stats.llm_used is False and stats.tokens == 0
    assert drafts["E2"].status == "not_found" and drafts["E3"].status == "partial"
    assert all(d.method == "local" for d in drafts.values()) and stats.fallback_cells == 2


def test_no_gateway_behaves_like_an_unavailable_llm():
    drafts, stats = chart_reference(None, "US1", {"E2": ELEMS["E2"]}, {"E2": [passage(0.7)]}, S)
    assert drafts["E2"].method == "local" and stats.error == "no gateway"


def test_element_without_passages_is_not_found_with_no_evidence():
    drafts, _ = chart_reference(StubGateway(), "US1", {"E1": ELEMS["E1"]}, {"E1": []}, S)
    cell = drafts["E1"]
    assert cell.status == "not_found" and cell.passage is None and cell.excerpt is None


def test_large_batches_are_split_to_respect_the_request_budget():
    big = " ".join(["word"] * 120)
    items = [{"e": f"E{i}", "t": "element", "ps": [{"id": f"E{i}.1", "t": big}, {"id": f"E{i}.2", "t": big}]}
             for i in range(1, 11)]  # fmt: skip
    overhead = estimate_tokens(prompts.CHART_CELLS.system) + prompts.CHART_CELLS.max_tokens + 100
    budget = S.llm_max_request_tokens - overhead
    batches = _batches(items, budget)
    assert len(batches) >= 2 and sum(len(b) for b in batches) == 10
    for batch in batches:  # every request fits the Groq per-request budget
        request = estimate_tokens(prompts.CHART_CELLS.system) + estimate_tokens(
            prompts.chart_cells_user("US1", batch)) + prompts.CHART_CELLS.max_tokens  # fmt: skip
        assert request < S.llm_max_request_tokens


def test_cell_input_hash_changes_with_anything_the_cell_depends_on():
    base = [passage(0.5)]
    key = cell_input_hash("element", base, S)
    assert key == cell_input_hash("element", [passage(0.5)], S)
    assert key == cell_input_hash("element", [passage(0.9)], S)  # score alone does not change it
    assert key != cell_input_hash("element changed", base, S)
    assert key != cell_input_hash("element", [passage(0.5, text="Different text.")], S)
    assert key != cell_input_hash("element", [passage(0.5, cid="US1:claim:9")], S)
    assert key != cell_input_hash("element", base, Settings(jwt_secret="x" * 40, fernet_key="x",
                                                            pipeline_low_threshold=0.3))  # fmt: skip


# ---- intake fallback ---------------------------------------------------------------------


def test_local_elements_split_the_solution_into_short_distinct_clauses():
    solution = (
        "A battery management unit measures cell impedance at several frequencies; a gas sensor "
        "detects electrolyte vapour in the pack housing, and a classifier combines the readings. "
        "A contactor is opened when the risk score exceeds a threshold."
    )
    elements = intake.local_elements("Detection is too late.", solution)
    assert 3 <= len(elements) <= 10 and len({e.lower() for e in elements}) == len(elements)
    assert all(3 <= len(e.split()) <= 25 for e in elements)
    assert any("gas sensor" in e for e in elements)
    assert intake.local_elements("", "") == []


def test_extract_elements_uses_the_llm_then_falls_back():
    from app.llm.prompts.models import ElementItem, ParseElementsOut

    class Gateway:
        def __init__(self, error=None):
            self.error = error

        def run(self, spec, user, **kwargs):
            if self.error:
                raise self.error
            value = ParseElementsOut(
                elements=[ElementItem(id="E1", text="first"), ElementItem(id="E2", text="second")]
            )
            return SimpleNamespace(value=value, total_tokens=321, provider="groq", cache_hit=False)

    fields = {"title": "T", "technical_field": "F", "problem": "Problem here is long enough.",
              "solution": "A unit measures impedance and a sensor detects gas near the cells."}  # fmt: skip
    ok = intake.extract_elements(Gateway(), **fields)
    assert (ok.elements, ok.source, ok.tokens, ok.provider) == (
        ["first", "second"],
        "llm",
        321,
        "groq",
    )
    local = intake.extract_elements(Gateway(LocalOnly("x")), **fields)
    assert local.source == "local" and local.fallback_reason == "local_only" and local.elements
    down = intake.extract_elements(Gateway(AllProvidersUnavailable("x")), **fields)
    assert down.source == "local" and down.fallback_reason == "AllProvidersUnavailable"
    assert intake.extract_elements(None, **fields).fallback_reason == "no gateway"


# ---- report helpers --------------------------------------------------------------------------


def test_drafting_considerations_are_questions_tied_to_the_chart():
    a = ref("A", [D, P, N, N, N])
    assessment = assess(KEYS, [a, ref("B", [N, N, N, D, N])])
    texts = {k: f"text of {k}" for k in KEYS}
    questions = drafting_considerations(assessment, texts)
    joined = "\n".join(questions)
    assert "E3" in joined and "E2" in joined and "partly disclosed" in joined
    assert all(q.endswith("?") or q.endswith(".") for q in questions) and len(questions) <= 8
    assert any("non-patent literature" in q for q in questions)
    anticipated = drafting_considerations(assess(KEYS, [ref("A", [D] * 5)]), texts)
    assert "A appears to disclose every element" in anticipated[0]
    combo = drafting_considerations(
        assess(KEYS, [ref("A", [D, D, D, N, N]), ref("B", [N, N, N, D, D])]), texts
    )
    assert "combination of A and B" in combo[0]


def test_template_summary_is_labelled_as_machine_generated():
    text = template_summary(assess(KEYS, [ref("A", [D, N, N, N, N])]))
    assert (
        text.startswith("Machine summary, no LLM.") and "Low" in text and "E2, E3, E4, E5" in text
    )


# ---- HTML / PDF export ---------------------------------------------------------------------------


def payload(**content_overrides):
    content = {
        "generated_by": "Machine summary, no LLM",
        "executive_summary": "Summary text.",
        "closest_references": [
            {
                "rank": 1,
                "patent_id": "US1",
                "title": "Battery <b>unit</b>",
                "assignee": "Acme",
                "source": "HUPD_APP",
                "publication_date": "2016-05-01",
                "coverage": {"disclosed": 1, "partial": 0, "not_found": 1},
            }
        ],  # fmt: skip
        "element_coverage": [
            {
                "element": "E1",
                "text": "gas sensor for vapour",
                "by_reference": {"US1": "disclosed"},
            },
            {"element": "E2", "text": "a contactor", "by_reference": {"US1": "not_found"}},
        ],  # fmt: skip
        "charts": [
            {
                "patent_id": "US1",
                "title": "Battery unit",
                "cells": [
                    {
                        "element": "E1",
                        "status": "disclosed",
                        "confidence": 0.93,
                        "method": "local",
                        "passage_id": "US1:claim:1",
                        "excerpt": "A gas sensor <script>alert(1)</script> detects vapour.",
                        "rationale": None,
                    }
                ],
            }
        ],  # fmt: skip
        "risk": {
            "level": "high",
            "score": 92,
            "basis": "US1 discloses all elements.",
            "uncovered_elements": [],
        },  # fmt: skip
        "claim_drafting_considerations": ["Is E2 supported?"],
        "limitations": ["Limited corpus."],
        "disclaimer": DISCLAIMER,
    }
    content.update(content_overrides)
    return {"case_id": "c", "title": "My <invention>", "state": "approved", "version": 2,
            "content_hash": "ab" * 32, "exported_at": "2026-10-13T12:00:00",
            "approval": {"approved_by": "Ada Attorney", "role": "attorney",
                         "approved_at": "2026-10-13T11:00:00+00:00", "version": 2,
                         "content_hash": "ab" * 32},
            "content": content}  # fmt: skip


def test_html_report_has_every_section_and_escapes_untrusted_text():
    html = export.render_report_html(payload())
    for heading in ("Executive summary", "Closest references", "Element coverage matrix",
                    "Novelty and obviousness risk", "Claim chart", "Considerations for claim drafting",
                    "Limitations", "Disclaimer"):  # fmt: skip
        assert heading in html
    assert DISCLAIMER in html and "Ada Attorney" in html and "High (92/100)" in html
    assert "<script>" not in html and "&lt;script&gt;" in html  # hostile excerpt is inert
    assert "My &lt;invention&gt;" in html and "Battery &lt;b&gt;unit" in html
    assert "<mark>gas</mark>" in html and "<mark>sensor</mark>" in html  # element words highlighted
    assert "[+] Disclosed" in html and "[-] Not found" in html  # status is not colour only
    assert "counter(pages)" in html  # page numbers in the PDF


def test_html_report_for_a_draft_and_for_sparse_edited_content():
    draft = payload()
    draft["approval"], draft["state"] = None, "draft"
    assert "Not approved" in export.render_report_html(draft)
    sparse = {"case_id": "c", "title": "T", "state": "draft", "version": 3, "content_hash": "00",
              "exported_at": "now", "approval": None, "content": {"note": "free text edit"}}  # fmt: skip
    html = export.render_report_html(sparse)  # must not raise on missing keys
    assert "No reference was charted" in html and "Not assessed" in html


def test_highlight_helper():
    assert (
        str(export.highlight("A gas sensor works.", "gas sensor"))
        == "A <mark>gas</mark> <mark>sensor</mark> works."
    )
    assert str(export.highlight("<b>gas</b>", "gas")) == "&lt;b&gt;<mark>gas</mark>&lt;/b&gt;"
    assert str(export.highlight(None, "x")) == "" and str(export.highlight("text", None)) == "text"


def test_pdf_rendering_produces_a_pdf_when_native_libraries_exist():
    try:
        pdf = export.html_to_pdf(export.render_report_html(payload()))
    except export.PdfUnavailable:
        pytest.skip("WeasyPrint native libraries (Pango) are not installed on this host")
    assert pdf.startswith(b"%PDF") and len(pdf) > 3000
