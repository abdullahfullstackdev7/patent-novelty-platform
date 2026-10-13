"""Report versions: deterministic draft builder, sealed storage and approval snapshots."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    Case,
    ChartCell,
    ClaimChart,
    DisclosureElement,
    Patent,
    Report,
    ReportVersion,
    SearchResult,
    SearchRun,
)
from app.security.crypto import open_json, seal_json
from app.services.disclosures import load_disclosure

DISCLAIMER = (
    "This report is decision support for a qualified patent attorney and is not legal advice. "
    "The search is limited to the indexed corpus and does not cover all prior art."
)
MACHINE_SUMMARY_NOTE = "Machine summary, no LLM"
CHART_REFERENCES = 3


def canonical_hash(content: dict[str, Any]) -> str:
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_report(session: Session, case_id: uuid.UUID) -> Report | None:
    return session.scalar(select(Report).where(Report.case_id == case_id))


def get_or_create_report(session: Session, case_id: uuid.UUID) -> Report:
    report = get_report(session, case_id)
    if report is None:
        report = Report(case_id=case_id, state="draft", current_version=0)
        session.add(report)
        session.flush()
    return report


def build_draft_content(session: Session, settings: Settings, case: Case) -> dict[str, Any]:
    """Template report from data already stored for the case. The LLM summary replaces the
    executive summary text in Phase 5, the structure stays the same."""
    disclosure = load_disclosure(session, settings, case.id)
    elements = disclosure.elements if disclosure else []

    run = session.scalar(
        select(SearchRun).where(SearchRun.case_id == case.id).order_by(SearchRun.created_at.desc())
    )
    references: list[dict[str, Any]] = []
    if run is not None:
        rows = session.execute(
            select(SearchResult, Patent)
            .join(Patent, Patent.id == SearchResult.patent_id, isouter=True)
            .where(SearchResult.run_id == run.id, SearchResult.excluded.is_(False))
            .order_by(SearchResult.rank)
            .limit(CHART_REFERENCES)
        ).all()
        references = [
            {
                "patent_id": result.patent_id,
                "title": patent.title if patent else None,
                "assignee": patent.assignee if patent else None,
                "source": patent.source if patent else None,
                "publication_date": patent.publication_date.isoformat() if patent else None,
                "score": round(result.score, 4),
            }
            for result, patent in rows
        ]

    coverage: list[dict[str, Any]] = []
    chart = session.scalar(select(ClaimChart).where(ClaimChart.case_id == case.id))
    cells: dict[tuple[str, str], str] = {}
    if chart is not None:
        keys = {
            e.id: e.key
            for e in session.scalars(
                select(DisclosureElement).where(
                    DisclosureElement.id.in_(
                        select(ChartCell.element_id).where(ChartCell.chart_id == chart.id)
                    )
                )
            )
        }
        for cell in session.scalars(select(ChartCell).where(ChartCell.chart_id == chart.id)):
            cells[(keys.get(cell.element_id, ""), cell.patent_id)] = cell.status
    for element in elements:
        coverage.append(
            {
                "element": element.key,
                "text": element.text,
                "by_reference": {
                    ref["patent_id"]: cells.get((element.key, ref["patent_id"]), "not_charted")
                    for ref in references
                },
            }
        )

    summary = (
        f"{MACHINE_SUMMARY_NOTE}. {len(references)} closest reference(s) retrieved for "
        f"{len(elements)} disclosure element(s). Risk level: {case.risk_level or 'not assessed'}."
    )
    return {
        "title": case.title,
        "generated_by": MACHINE_SUMMARY_NOTE,
        "executive_summary": summary,
        "closest_references": references,
        "element_coverage": coverage,
        "risk": {
            "level": case.risk_level,
            "score": float(case.risk_score) if case.risk_score is not None else None,
        },
        "limitations": [
            "The search covers only the indexed corpus.",
            "Passage matching is automated and must be confirmed by an attorney.",
        ],
        "disclaimer": DISCLAIMER,
    }


def add_version(
    session: Session,
    settings: Settings,
    report: Report,
    content: dict[str, Any],
    user_id: uuid.UUID,
) -> ReportVersion:
    """Store a new version. The content is encrypted, the hash is over the plaintext."""
    report.current_version += 1
    version = ReportVersion(
        report_id=report.id,
        version=report.current_version,
        content=seal_json(content, settings),
        content_hash=canonical_hash(content),
        created_by=user_id,
    )
    session.add(version)
    session.flush()
    return version


def get_version(
    session: Session, report: Report, number: int | None = None
) -> ReportVersion | None:
    target = number or report.current_version
    return session.scalar(
        select(ReportVersion).where(
            ReportVersion.report_id == report.id, ReportVersion.version == target
        )
    )


def read_content(settings: Settings, version: ReportVersion) -> dict[str, Any]:
    return open_json(version.content, settings)
