"""Load the charted references of a case and compute the risk assessment from stored cells."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ChartCell,
    ClaimChart,
    Disclosure,
    DisclosureElement,
    Patent,
    SearchResult,
    SearchRun,
)
from app.pipeline import risk


@dataclass
class ReferenceInfo:
    patent_id: str
    rank: int
    score: float
    title: str | None
    assignee: str | None
    source: str | None
    publication_date: date | None
    cpc_subclasses: tuple[str, ...]
    url: str | None


def latest_run(session: Session, case_id: uuid.UUID) -> SearchRun | None:
    return session.scalar(
        select(SearchRun).where(SearchRun.case_id == case_id).order_by(SearchRun.created_at.desc())
    )


def charted_references(session: Session, case_id: uuid.UUID) -> list[ReferenceInfo]:
    """References selected for the chart in the latest search run, best first."""
    run = latest_run(session, case_id)
    if run is None:
        return []
    rows = session.execute(
        select(SearchResult, Patent)
        .join(Patent, Patent.id == SearchResult.patent_id, isouter=True)
        .where(SearchResult.run_id == run.id, SearchResult.in_chart.is_(True),
               SearchResult.excluded.is_(False))
        .order_by(SearchResult.rank)
    ).all()  # fmt: skip
    return [
        ReferenceInfo(
            r.patent_id, r.rank, r.score,
            p.title if p else None, p.assignee if p else None, p.source if p else None,
            p.publication_date if p else None,
            tuple(p.cpc_subclasses) if p else (), p.url if p else None,
        )
        for r, p in rows
    ]  # fmt: skip


def element_keys(session: Session, case_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    """(element id, key) in disclosure order."""
    return [
        (row.id, row.key)
        for row in session.execute(
            select(DisclosureElement.id, DisclosureElement.key)
            .join(Disclosure, Disclosure.id == DisclosureElement.disclosure_id)
            .where(Disclosure.case_id == case_id)
            .order_by(DisclosureElement.position)
        )
    ]


def cells_by_reference(session: Session, case_id: uuid.UUID) -> dict[str, dict[str, ChartCell]]:
    """patent id -> element key -> cell, for the case's chart."""
    chart = session.scalar(select(ClaimChart).where(ClaimChart.case_id == case_id))
    if chart is None:
        return {}
    keys = {eid: key for eid, key in element_keys(session, case_id)}
    grouped: dict[str, dict[str, ChartCell]] = {}
    for cell in session.scalars(select(ChartCell).where(ChartCell.chart_id == chart.id)):
        key = keys.get(cell.element_id)
        if key is not None:
            grouped.setdefault(cell.patent_id, {})[key] = cell
    return grouped


def load_assessment(
    session: Session, case_id: uuid.UUID
) -> tuple[risk.RiskAssessment, list[ReferenceInfo]]:
    keys = [key for _, key in element_keys(session, case_id)]
    references = charted_references(session, case_id)
    grouped = cells_by_reference(session, case_id)
    refs = [
        risk.RefCells(
            ref.patent_id,
            ref.cpc_subclasses,
            {k: c.status for k, c in grouped.get(ref.patent_id, {}).items()},
            {k: float(c.confidence) for k, c in grouped.get(ref.patent_id, {}).items()},
        )
        for ref in references
    ]
    return risk.assess(keys, refs), references
