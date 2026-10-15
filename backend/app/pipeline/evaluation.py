"""Chart quality check (Phase 10): compare automatic cell verdicts with human labels and tune thresholds.

A labelled row is one element against one reference passage, with the status a person judged
(disclosed, partial or not_found), the cosine similarity and keyword overlap the pipeline
computed, and optionally the verdict the language model gave. The threshold sweep re-runs the
local pre-classifier with other cut-offs and reports how often the final verdict matches the
person and how many pairs would still be sent to the model.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from itertools import product
from pathlib import Path

from app.config import Settings
from app.pipeline.classify import NOT_FOUND, local_fallback, pre_classify

STATUSES = ("disclosed", "partial", "not_found")
COLUMNS = ("element", "passage", "human_status", "cosine", "overlap", "llm_status")


@dataclass(frozen=True)
class LabelledPair:
    element: str
    passage: str
    human: str
    cosine: float
    overlap: float
    llm: str | None = None


def load_labels(path: Path) -> list[LabelledPair]:
    rows: list[LabelledPair] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            human = (row.get("human_status") or "").strip()
            if not human:
                continue  # not labelled yet
            if human not in STATUSES:
                raise ValueError(f"line {number}: human_status must be one of {', '.join(STATUSES)}")
            llm = (row.get("llm_status") or "").strip() or None
            if llm is not None and llm not in STATUSES:
                raise ValueError(f"line {number}: llm_status must be one of {', '.join(STATUSES)}")
            rows.append(
                LabelledPair(
                    row["element"], row["passage"], human, float(row["cosine"]), float(row["overlap"]), llm
                )
            )
    return rows


def write_template(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(COLUMNS)


def accuracy(predicted: list[str], gold: list[str]) -> float:
    return sum(p == g for p, g in zip(predicted, gold, strict=True)) / len(gold) if gold else 0.0


def cohen_kappa(predicted: list[str], gold: list[str]) -> float:
    """Agreement beyond chance. 1 is perfect, 0 is what guessing from the label mix would give."""
    n = len(gold)
    if n == 0:
        return 0.0
    observed = accuracy(predicted, gold)
    p_counts, g_counts = Counter(predicted), Counter(gold)
    expected = sum(p_counts[s] * g_counts[s] for s in STATUSES) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def confusion(predicted: list[str], gold: list[str]) -> dict[str, dict[str, int]]:
    table = {g: dict.fromkeys(STATUSES, 0) for g in STATUSES}
    for p, g in zip(predicted, gold, strict=True):
        table[g][p] += 1
    return table


def final_verdict(pair: LabelledPair, settings: Settings) -> tuple[str, bool]:
    """(verdict, sent_to_llm) under the given settings, mirroring the pipeline."""
    local = pre_classify(pair.cosine, pair.overlap, settings)
    if local is not None:
        return local, False
    return (pair.llm if pair.llm is not None else local_fallback(pair.cosine, settings)), True


@dataclass
class SweepRow:
    low: float
    high: float
    accuracy: float
    kappa: float
    llm_share: float


def sweep_thresholds(
    pairs: list[LabelledPair],
    base: Settings,
    lows: tuple[float, ...] = (0.25, 0.30, 0.35, 0.40, 0.45),
    highs: tuple[float, ...] = (0.80, 0.84, 0.88, 0.92),
) -> list[SweepRow]:
    """Every (low, high) combination, best agreement first. Ties go to the one that calls the model less."""
    out: list[SweepRow] = []
    gold = [p.human for p in pairs]
    for low, high in product(lows, highs):
        if low >= high:
            continue
        settings = base.model_copy(update={"pipeline_low_threshold": low, "pipeline_high_threshold": high})
        verdicts = [final_verdict(p, settings) for p in pairs]
        predicted = [v for v, _ in verdicts]
        share = sum(1 for _, sent in verdicts if sent) / len(pairs) if pairs else 0.0
        out.append(SweepRow(low, high, accuracy(predicted, gold), cohen_kappa(predicted, gold), share))
    return sorted(out, key=lambda r: (-r.accuracy, r.llm_share, r.low, r.high))


def agreement_report(pairs: list[LabelledPair], settings: Settings) -> dict[str, object]:
    """Agreement of the pre-classifier on its own cells and of the model on the cells it judged."""
    gold = [p.human for p in pairs]
    verdicts = [final_verdict(p, settings) for p in pairs]
    local = [(p, v) for p, (v, sent) in zip(pairs, verdicts, strict=True) if not sent]
    judged = [p for p, (_, sent) in zip(pairs, verdicts, strict=True) if sent and p.llm is not None]
    return {
        "pairs": len(pairs),
        "overall_accuracy": accuracy([v for v, _ in verdicts], gold),
        "overall_kappa": cohen_kappa([v for v, _ in verdicts], gold),
        "local_cells": len(local),
        "local_accuracy": accuracy([v for _, v in local], [p.human for p, _ in local]),
        "llm_cells": len(judged),
        "llm_accuracy": accuracy([p.llm or NOT_FOUND for p in judged], [p.human for p in judged]),
        "confusion": confusion([v for v, _ in verdicts], gold),
    }
