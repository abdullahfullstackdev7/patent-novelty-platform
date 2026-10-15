"""Search quality metrics against examiner citations (Phase 10).

Ground truth: for a granted patent in the corpus, the references its examiner cited. Only
references that are themselves in the corpus can be found, so the others are dropped before
scoring. Metrics are recall at K (share of the cited references found in the top K) and the
mean reciprocal rank of the first cited reference.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

KS = (10, 50, 100)
_NUMBER = re.compile(r"\d+")
_KIND_CODE = re.compile(r"[A-Za-z]\d?\s*$")


def normalize_patent_number(value: str) -> str:
    """Both 'US 10,123,456 B2' and '10123456' become '10123456'. Letters and punctuation are dropped."""
    without_kind = _KIND_CODE.sub("", (value or "").strip())  # B2, A1 and similar suffixes
    digits = "".join(_NUMBER.findall(without_kind))
    return digits.lstrip("0")


def load_examiner_citations(path: Path) -> dict[str, set[str]]:
    """Read a PatentsView g_us_patent_citation TSV into {patent number: {cited patent numbers}}.

    Only rows the examiner added count. Applicant citations say little about what the examiner
    considered the closest art.
    """
    cited: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            category = (row.get("citation_category") or "").lower()
            if "examiner" not in category:
                continue
            source = normalize_patent_number(row.get("patent_id", ""))
            target = normalize_patent_number(row.get("citation_patent_id", ""))
            if source and target and source != target:
                cited[source].add(target)
    return dict(cited)


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Share of the relevant items that appear in the first k results. 0 when there are none."""
    if not relevant:
        return 0.0
    return len(relevant.intersection(ranked[:k])) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for position, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / position
    return 0.0


@dataclass
class QueryResult:
    patent_id: str
    relevant: int
    recall: dict[int, float]
    rr: float


@dataclass
class Summary:
    queries: int
    recall: dict[int, float]
    mrr: float
    per_query: list[QueryResult] = field(default_factory=list)

    def as_markdown(self) -> str:
        rows = "\n".join(f"| recall@{k} | {self.recall[k]:.3f} |" for k in sorted(self.recall))
        return f"| metric | value |\n|---|---|\n{rows}\n| MRR | {self.mrr:.3f} |\n| queries | {self.queries} |"


def evaluate(
    cases: Iterable[tuple[str, set[str]]],
    search: Callable[[str], list[str]],
    ks: tuple[int, ...] = KS,
) -> Summary:
    """Run `search(patent_id)` for each case and score the ranked patent ids it returns.

    The patent used as the query is removed from its own results, since it is not prior art for
    itself.
    """
    results: list[QueryResult] = []
    for patent_id, relevant in cases:
        ranked = [p for p in search(patent_id) if p != patent_id]
        results.append(
            QueryResult(
                patent_id,
                len(relevant),
                {k: recall_at_k(ranked, relevant, k) for k in ks},
                reciprocal_rank(ranked, relevant),
            )
        )
    n = len(results)

    def mean(values: list[float]) -> float:
        return sum(values) / n if n else 0.0

    return Summary(
        queries=n,
        recall={k: mean([r.recall[k] for r in results]) for k in ks},
        mrr=mean([r.rr for r in results]),
        per_query=results,
    )


def pick_cases(
    corpus_numbers: dict[str, str], citations: dict[str, set[str]], limit: int
) -> list[tuple[str, set[str]]]:
    """Choose patents that have at least one examiner citation inside the corpus.

    `corpus_numbers` maps a corpus patent id to its normalised number. Cited numbers are translated
    back to corpus ids, and patents are taken in id order so the selection is repeatable.
    """
    by_number = {number: pid for pid, number in corpus_numbers.items()}
    cases: list[tuple[str, set[str]]] = []
    for pid in sorted(corpus_numbers):
        wanted = citations.get(corpus_numbers[pid], set())
        present = {by_number[n] for n in wanted if n in by_number}
        if present:
            cases.append((pid, present))
        if len(cases) >= limit:
            break
    return cases
