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
    Report,
    ReportVersion,
)
from app.pipeline import risk
from app.pipeline.assessment import cells_by_reference, load_assessment
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


def _short(text: str, words: int = 12) -> str:
    parts = text.split()
    return text if len(parts) <= words else " ".join(parts[:words]) + " ..."


def drafting_considerations(assessment: risk.RiskAssessment, texts: dict[str, str]) -> list[str]:
    """Questions for the attorney, derived from the chart. Never conclusions."""
    questions: list[str] = []
    if assessment.anticipation_reference:
        questions.append(
            f"{assessment.anticipation_reference} appears to disclose every element. Should the "
            "claims be narrowed with a feature it lacks, or is another position available?"
        )
    elif assessment.combination:
        questions.append(
            f"The combination of {' and '.join(assessment.combination)} appears to cover every "
            "element. Is there a reason a skilled person would not combine them?"
        )
    for row in assessment.per_element:
        label = f"{row.element} ({_short(texts.get(row.element, ''))})"
        if row.novel and not row.partial_in:
            questions.append(
                f"No charted reference discloses {label}. Is it supported in the specification as "
                "a distinguishing feature, and should an independent claim recite it?"
            )
        elif row.novel:
            questions.append(
                f"{label} is only partly disclosed (in {', '.join(row.partial_in)}). Can the claim "
                "language be drawn to distinguish the partial disclosure?"
            )
    questions.append(
        "Were non-patent literature and foreign patents searched? The index covers only the "
        "loaded US corpus."
    )
    return questions[:8]


def template_summary(assessment: risk.RiskAssessment) -> str:
    uncovered = ", ".join(assessment.uncovered_elements) or "none"
    return (
        f"{MACHINE_SUMMARY_NOTE}. Risk assessment: {assessment.label} "
        f"({assessment.score}/100). {assessment.basis} "
        f"Elements not disclosed by any charted reference: {uncovered}."
    )


def build_draft_content(
    session: Session,
    settings: Settings,
    case: Case,
    *,
    summary: str | None = None,
    llm_used: bool = False,
) -> dict[str, Any]:
    """Report content from the stored chart and risk. Fully deterministic for the same inputs,
    so an unchanged case yields an identical hash and no new version.

    `summary` is the LLM executive summary when one was produced, otherwise a template text
    labelled 'Machine summary, no LLM' is used.
    """
    disclosure = load_disclosure(session, settings, case.id)
    elements = disclosure.elements if disclosure else []
    texts = {e.key: e.text for e in elements}
    assessment, references = load_assessment(session, case.id)
    grouped = cells_by_reference(session, case.id)

    ref_rows = [
        {
            "rank": ref.rank,
            "patent_id": ref.patent_id,
            "title": ref.title,
            "assignee": ref.assignee,
            "source": ref.source,
            "publication_date": ref.publication_date.isoformat() if ref.publication_date else None,
            "cpc_subclasses": list(ref.cpc_subclasses),
            "url": ref.url,
            "score": round(ref.score, 4),
            "coverage": assessment.coverage.get(ref.patent_id, {}),
        }
        for ref in references
    ]
    coverage = [
        {
            "element": element.key,
            "text": element.text,
            "by_reference": {
                ref.patent_id: (grouped.get(ref.patent_id, {}).get(element.key).status
                                if grouped.get(ref.patent_id, {}).get(element.key) else "not_charted")
                for ref in references
            },
        }
        for element in elements
    ]  # fmt: skip
    charts = [
        {
            "patent_id": ref.patent_id,
            "title": ref.title,
            "cells": [
                {
                    "element": element.key,
                    "status": cell.status,
                    "confidence": float(cell.confidence),
                    "method": cell.method,
                    "passage_id": cell.passage_id,
                    "excerpt": cell.excerpt,
                    "char_start": cell.char_start,
                    "char_end": cell.char_end,
                    "rationale": cell.rationale,
                }
                for element in elements
                if (cell := grouped.get(ref.patent_id, {}).get(element.key)) is not None
            ],
        }
        for ref in references
    ]
    return {
        "title": case.title,
        "generated_by": "LLM-assisted summary" if llm_used and summary else MACHINE_SUMMARY_NOTE,
        "llm": {"used": bool(llm_used and summary)},
        "executive_summary": summary or template_summary(assessment),
        "closest_references": ref_rows,
        "element_coverage": coverage,
        "charts": charts,
        "risk": {
            "level": assessment.level,
            "label": assessment.label,
            "score": assessment.score,
            "basis": assessment.basis,
            "anticipation_reference": assessment.anticipation_reference,
            "combination": assessment.combination,
            "uncovered_elements": assessment.uncovered_elements,
            "per_element": [
                {
                    "element": r.element,
                    "disclosed_by": r.disclosed_by,
                    "partial_in": r.partial_in,
                    "novel": r.novel,
                }
                for r in assessment.per_element
            ],  # fmt: skip
        },
        "claim_drafting_considerations": drafting_considerations(assessment, texts),
        "limitations": [
            "The search covers only the indexed corpus, not all prior art.",
            "Passage matching is automated. Cells marked local or LLM must be confirmed by an attorney.",
            "Risk levels follow fixed rules over the chart and are not a legal opinion.",
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
