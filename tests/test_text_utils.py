import pytest
from text_utils import chunk_passages, classify_claim, clean_text, parse_claims, split_sentences


def test_clean_text_collapses_whitespace_and_control_chars():
    assert clean_text("  a\x00b \n\t c  ") == "a b c"
    assert clean_text(None) == ""


def test_parse_claims_basic_and_dependency():
    raw = (
        "1. A method comprising: receiving data. "
        "2. The method of claim 1, wherein the data is encrypted. "
        "3. A system configured to perform the method of any of claims 1 or 2."
    )
    claims = parse_claims(raw)
    assert [c.number for c in claims] == [1, 2, 3]
    assert claims[0].is_independent and claims[0].parent is None
    assert not claims[1].is_independent and claims[1].parent == 1
    assert claims[2].parent == 1
    assert claims[0].text.startswith("A method")


def test_parse_claims_ignores_numbers_inside_claim_bodies():
    raw = "1. A device of 2. 5 mm width. 2. The device of claim 1, wherein it is 3 mm wide."
    assert [c.number for c in parse_claims(raw)] == [1, 2]


def test_parse_claims_starts_above_one_and_drops_canceled_ranges():
    raw = "1-20. (canceled) 21. A system for monitoring. 22. The system of claim 21, further X."
    claims = parse_claims(raw)
    assert [c.number for c in claims] == [21, 22]
    assert claims[0].is_independent and claims[1].parent == 21


def test_parse_claims_en_dash_range_is_normalized():
    raw = f"1{chr(0x2013)}2. (canceled) 3. A system for monitoring."
    assert [c.number for c in parse_claims(raw)] == [3]


def test_parse_claims_drops_single_canceled_claim_and_keeps_gap():
    raw = "1. A method. 2. (canceled) 3. The method of claim 1, wherein Y."
    assert [c.number for c in parse_claims(raw)] == [1, 3]


def test_parse_claims_without_numbering_returns_one_claim():
    claims = parse_claims("What is claimed is: A widget comprising a body.")
    assert len(claims) == 1 and claims[0].text == "A widget comprising a body."


def test_parse_claims_empty():
    assert parse_claims("") == []
    assert parse_claims(None) == []


@pytest.mark.parametrize(
    ("number", "text", "expected"),
    [
        (2, "The method of claim 1, wherein x.", (False, 1)),
        (5, "A system as described in claim 4, wherein x.", (False, 4)),
        (3, "A method comprising steps.", (True, None)),
        (1, "A method of claim 9 is not earlier.", (True, None)),
    ],
)
def test_classify_claim(number, text, expected):
    assert classify_claim(number, text) == expected


def test_split_sentences_skips_abbreviations():
    text = "See FIG. 3 for details. The value is e.g. 5. Next sentence follows here."
    spans = [text[s:e] for s, e in split_sentences(text)]
    assert spans[0] == "See FIG. 3 for details."
    assert len(spans) == 3


def _sentence(i: int) -> str:
    return " ".join(f"word{i}x{j}" for j in range(20)) + "."


def test_chunk_passages_offsets_are_exact_and_bounded():
    text = " ".join(_sentence(i) for i in range(40))  # 800 words
    passages = chunk_passages(text)
    assert passages
    for passage, start, end in passages:
        assert text[start:end] == passage
        assert 15 <= len(passage.split()) <= 150
    assert sum(len(p.split()) for p, _, _ in passages) == 800  # nothing dropped


def test_chunk_passages_splits_overlong_sentence():
    text = " ".join(f"w{i}" for i in range(400)) + "."
    passages = chunk_passages(text)
    assert all(len(p.split()) <= 150 for p, _, _ in passages)
    assert all(text[s:e] == p for p, s, e in passages)


def test_chunk_passages_drops_tiny_fragments():
    assert chunk_passages("2.") == []
    assert chunk_passages("") == []


def test_claim_referencing_canceled_parent_becomes_independent():
    raw = (
        "1-10. (canceled) 11. A method using the device of claim 1. 12. The method of claim 11, X."
    )
    claims = parse_claims(raw)
    assert [(c.number, c.is_independent, c.parent) for c in claims] == [
        (11, True, None),
        (12, False, 11),
    ]


def test_parse_claims_range_with_dot_before_dash():
    assert [c.number for c in parse_claims("1.-24. (canceled) 25. A system, comprising: X.")] == [
        25
    ]
    raw = "1. A method. 2. B. 3.-4. (canceled) 5. The method of claim 1, Y."
    assert [c.number for c in parse_claims(raw)] == [1, 2, 5]


def test_clean_text_replaces_long_dashes():
    assert clean_text(f"a{chr(0x2014)}b {chr(0x2013)} c") == "a-b - c"
