"""Deterministic novelty and obviousness risk from the claim chart (no LLM).

Rules (section 5, Phase 5):
  anticipation, 35 U.S.C. 102 style: one reference discloses every element -> high.
  obviousness, 103 style: two or three references together disclose every element, or one
    reference discloses at least 80 percent and the remaining elements are partial in it ->
    medium_high if the references share a CPC subclass, otherwise medium.
  otherwise low, and the elements no reference discloses are the points of novelty.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

DISCLOSED, PARTIAL, NOT_FOUND = "disclosed", "partial", "not_found"
HIGH, MEDIUM_HIGH, MEDIUM, LOW = "high", "medium_high", "medium", "low"
BANDS = {LOW: (0, 35), MEDIUM: (36, 64), MEDIUM_HIGH: (65, 84), HIGH: (85, 100)}
LABELS = {LOW: "Low", MEDIUM: "Medium", MEDIUM_HIGH: "Medium-High", HIGH: "High"}
SINGLE_REFERENCE_SHARE = 0.8
WEIGHT = {DISCLOSED: 1.0, PARTIAL: 0.5, NOT_FOUND: 0.0}


@dataclass(frozen=True)
class RefCells:
    """One charted reference: status and confidence per element key."""

    patent_id: str
    cpc_subclasses: tuple[str, ...]
    status: dict[str, str]
    confidence: dict[str, float] = field(default_factory=dict)


@dataclass
class ElementRow:
    element: str
    disclosed_by: list[str]
    partial_in: list[str]

    @property
    def novel(self) -> bool:
        """No charted reference discloses this element (it may still be partly disclosed)."""
        return not self.disclosed_by


@dataclass
class RiskAssessment:
    level: str
    score: int
    basis: str
    anticipation_reference: str | None = None
    combination: list[str] = field(default_factory=list)
    shared_subclasses: list[str] = field(default_factory=list)
    uncovered_elements: list[str] = field(default_factory=list)
    per_element: list[ElementRow] = field(default_factory=list)
    coverage: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return LABELS[self.level]


def _disclosed(ref: RefCells, elements: list[str]) -> set[str]:
    return {e for e in elements if ref.status.get(e) == DISCLOSED}


def _strength(elements: list[str], decisive: list[RefCells]) -> float:
    """Mean over elements of the best (status weight x confidence) among the decisive refs."""
    if not elements:
        return 0.0
    total = 0.0
    for element in elements:
        best = 0.0
        for ref in decisive:
            status = ref.status.get(element, NOT_FOUND)
            best = max(best, WEIGHT[status] * ref.confidence.get(element, 1.0))
        total += best
    return total / len(elements)


def _score(level: str, elements: list[str], decisive: list[RefCells]) -> int:
    low, high = BANDS[level]
    return round(low + (high - low) * _strength(elements, decisive))


def assess(elements: list[str], refs: list[RefCells]) -> RiskAssessment:
    """Assess risk for `elements` (keys in order) against the charted references."""
    rows = [
        ElementRow(
            e,
            [r.patent_id for r in refs if r.status.get(e) == DISCLOSED],
            [r.patent_id for r in refs if r.status.get(e) == PARTIAL],
        )
        for e in elements
    ]
    uncovered = [row.element for row in rows if row.novel]
    coverage = {
        r.patent_id: {
            s: sum(1 for e in elements if r.status.get(e, NOT_FOUND) == s)
            for s in (DISCLOSED, PARTIAL, NOT_FOUND)
        }
        for r in refs
    }
    result = RiskAssessment(
        LOW, 0, "", uncovered_elements=uncovered, per_element=rows, coverage=coverage
    )

    if not elements or not refs:
        result.basis = "No charted reference, so no prior-art risk could be assessed."
        return result

    everything = set(elements)
    for ref in refs:
        if _disclosed(ref, elements) == everything:
            result.level = HIGH
            result.anticipation_reference = ref.patent_id
            result.score = _score(HIGH, elements, [ref])
            result.basis = (
                f"Reference {ref.patent_id} discloses all {len(elements)} elements "
                "(anticipation risk)."
            )
            return result

    combos: list[tuple[bool, int, list[RefCells], list[str]]] = []
    for ref in refs:
        found = _disclosed(ref, elements)
        rest = everything - found
        if len(found) / len(elements) >= SINGLE_REFERENCE_SHARE and all(
            ref.status.get(e) == PARTIAL for e in rest
        ):
            combos.append((True, 1, [ref], list(ref.cpc_subclasses)))
    for size in (2, 3):
        for group in itertools.combinations(refs, size):
            union = set().union(*(_disclosed(r, elements) for r in group))
            if union == everything:
                shared = set.intersection(*(set(r.cpc_subclasses) for r in group))
                combos.append((bool(shared), size, list(group), sorted(shared)))

    if combos:
        # best: shared CPC subclass first, then the smallest combination
        same_class, size, group, shared = sorted(combos, key=lambda c: (not c[0], c[1]))[0]
        result.level = MEDIUM_HIGH if same_class else MEDIUM
        result.combination = [r.patent_id for r in group]
        result.shared_subclasses = list(shared) if same_class else []
        result.score = _score(result.level, elements, group)
        names = " and ".join(result.combination)
        where = (
            f"in CPC subclass {', '.join(result.shared_subclasses)}"
            if same_class
            else "across different CPC subclasses"
        )
        what = "covers" if size > 1 else "nearly covers"
        result.basis = f"{names} {what} all elements {where} (obviousness risk)."
        return result

    result.level = LOW
    result.score = _score(LOW, elements, refs)
    listed = ", ".join(uncovered) if uncovered else "none"
    result.basis = (
        f"No reference or combination of up to three references discloses every element. "
        f"Elements disclosed by no reference: {listed}."
    )
    return result
