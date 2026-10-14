"""The eight sample disclosures: well-formed, loadable, and inside the token budgets."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.config import Settings
from app.llm import prompts
from app.llm.budget import estimate_tokens
from app.pipeline.charting import ELEMENT_WORDS, _batches
from app.search.cli import load_disclosure

DIRECTORY = Path(__file__).resolve().parents[2] / "dataset" / "disclosures"
FILES = sorted(DIRECTORY.glob("*.json"))
S = Settings()
EXPECTED_TOPICS = (
    "federated", "thermal runaway", "cold-chain", "atrial fibrillation",
    "clinical notes", "vehicle-to-grid", "zero-trust", "depolymerising",
)  # fmt: skip


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_there_are_eight_samples_covering_the_planned_topics():
    assert len(FILES) == 8
    titles = " ".join(read(p)["title"].lower() for p in FILES)
    missing = [topic for topic in EXPECTED_TOPICS if topic not in titles]
    assert missing == [], f"no sample for: {missing}"


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_each_sample_is_well_formed(path):
    data = read(path)
    assert {"title", "technical_field", "problem", "solution", "elements", "priority_date"} <= set(
        data
    )
    assert 6 <= len(data["elements"]) <= 10
    assert [e["id"] for e in data["elements"]] == [
        f"E{i}" for i in range(1, len(data["elements"]) + 1)
    ]
    assert all(5 <= len(e["text"].split()) <= 40 for e in data["elements"])
    assert date.fromisoformat(data["priority_date"]) > date(2017, 12, 31)  # after the demo corpus
    assert data["synthetic"] is True and data["jurisdiction"] == "US"
    assert data["dependent_features"]
    text = path.read_text(encoding="utf-8")
    assert "—" not in text and "–" not in text  # house style: no long dashes
    markdown = path.with_suffix(".md")
    assert markdown.exists() and data["title"] in markdown.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_samples_load_as_search_queries(path):
    query = load_disclosure(path)
    data = read(path)
    assert query.title == data["title"] and len(query.elements) == len(data["elements"])
    assert data["problem"] in query.summary and data["solution"] in query.summary
    assert query.priority_date == date.fromisoformat(data["priority_date"])


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_extraction_request_fits_the_groq_budget(path):
    data = read(path)
    user = prompts.parse_elements_user(
        data["title"], data["technical_field"], data["problem"], data["solution"]
    )
    spec = prompts.PARSE_ELEMENTS
    request = estimate_tokens(spec.system) + estimate_tokens(user) + spec.max_tokens
    assert request < S.llm_max_request_tokens
    assert (
        estimate_tokens(spec.system) + estimate_tokens(user) < 1000
    )  # the plan expects 1,200 to 1,800 in+out


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_worst_case_chart_requests_each_fit_the_per_request_budget(path):
    """Even if every element were ambiguous, no single request exceeds the Groq budget."""
    data = read(path)
    passage = " ".join(["word"] * S.pipeline_passage_words)
    items = [
        {"e": e["id"], "t": " ".join(e["text"].split()[:ELEMENT_WORDS]),
         "ps": [{"id": f"{e['id']}.{n}", "t": passage} for n in (1, 2)]}
        for e in data["elements"]
    ]  # fmt: skip
    spec = prompts.CHART_CELLS
    overhead = estimate_tokens(spec.system) + spec.max_tokens + 100
    batches = _batches(items, S.llm_max_request_tokens - overhead)
    for batch in batches:
        user = prompts.chart_cells_user("US1", batch)
        assert (
            estimate_tokens(spec.system) + estimate_tokens(user) + spec.max_tokens
            < S.llm_max_request_tokens
        )
    assert sum(len(b) for b in batches) == len(items) and len(batches) <= 4


def test_expected_case_stays_well_under_the_nine_thousand_token_target():
    """Per case: extraction + 3 references (about 30 percent of pairs ambiguous) + summary.

    This is an estimate from the real prompt sizes. The measured median is part of Phase 10.
    """
    medians = []
    for path in FILES:
        data = read(path)
        n = len(data["elements"])
        ambiguous = max(1, round(n * 0.3))
        passage = " ".join(["word"] * S.pipeline_passage_words)
        total = 0
        extraction_user = prompts.parse_elements_user(
            data["title"], data["technical_field"], data["problem"], data["solution"]
        )
        total += (
            estimate_tokens(prompts.PARSE_ELEMENTS.system)
            + estimate_tokens(extraction_user)
            + 40 * n
        )
        items = [{"e": f"E{i}", "t": data["elements"][i - 1]["text"],
                  "ps": [{"id": f"E{i}.{k}", "t": passage} for k in (1, 2)]}
                 for i in range(1, ambiguous + 1)]  # fmt: skip
        per_reference = (estimate_tokens(prompts.CHART_CELLS.system)
                         + estimate_tokens(prompts.chart_cells_user("US1", items)) + 45 * ambiguous)  # fmt: skip
        total += 3 * per_reference
        facts = {"risk": "low", "score": 20, "refs": ["US1", "US2", "US3"],
                 "elements": [{"e": f"E{i}", "disclosed_by": ["US1"], "partial_in": ["US2"]} for i in range(1, n + 1)]}  # fmt: skip
        total += (
            estimate_tokens(prompts.EXEC_SUMMARY.system)
            + estimate_tokens(prompts.exec_summary_user(facts))
            + 450
        )
        medians.append(total)
    medians.sort()
    assert medians[len(medians) // 2] < 9000
    assert max(medians) < 12000
