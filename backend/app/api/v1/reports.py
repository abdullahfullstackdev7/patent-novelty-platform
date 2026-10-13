"""Reports, versions, attorney review and export."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.deps import PrincipalDep, SessionDep, SettingsDep, ip_of
from app.api.v1.cases import ensure_editable
from app.api.v1.schemas import (
    ChangesRequest,
    ReportEdit,
    ReportOut,
    ReviewComment,
    ReviewEventOut,
    VersionInfo,
)
from app.db.models import Case, Report, ReportVersion, ReviewEvent, Role, User
from app.security import policy
from app.services import audit
from app.services import reports as report_service
from app.services.access import forbidden, load_case, not_found

router = APIRouter(tags=["report"])

MAX_REPORT_CHARS = 200_000


def _approval(session, version: ReportVersion) -> dict[str, Any] | None:
    """The approval stamp: who, in which role, when, which version and its hash."""
    if version.approved_at is None or version.approved_by is None:
        return None
    approver = session.get(User, version.approved_by)
    role = session.get(Role, approver.role_id) if approver else None
    return {
        "approved_by": approver.full_name if approver else None,
        "role": role.name if role else None,
        "approved_at": version.approved_at.isoformat(),
        "version": version.version,
        "content_hash": version.content_hash,
    }


def _report_out(session, settings, report: Report, version: ReportVersion) -> ReportOut:
    versions = session.scalars(
        select(ReportVersion)
        .where(ReportVersion.report_id == report.id)
        .order_by(ReportVersion.version)
    ).all()
    return ReportOut(
        state=report.state,
        version=version.version,
        content_hash=version.content_hash,
        content=report_service.read_content(settings, version),
        versions=[
            VersionInfo(
                version=v.version, content_hash=v.content_hash, created_at=v.created_at,
                approved_at=v.approved_at,
            )
            for v in versions
        ],
        approval=_approval(session, version),
    )  # fmt: skip


def _event(case_id, user_id, kind: str, comment: str | None = None) -> ReviewEvent:
    return ReviewEvent(case_id=case_id, user_id=user_id, event_type=kind, comment=comment)


def _require_report(session, case_id: uuid.UUID) -> Report:
    report = report_service.get_report(session, case_id)
    if report is None or report.current_version == 0:
        raise not_found()
    return report


def _require_writable_report(case: Case, report: Report | None) -> None:
    ensure_editable(case)
    if report is not None and report.state == "in_review":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The report is in review. Request changes to edit it"
        )


# ---- report -------------------------------------------------------------------


@router.post(
    "/cases/{case_id}/report", response_model=ReportOut, status_code=status.HTTP_201_CREATED
)
def generate_report(
    case_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ReportOut:
    """Build a new draft version from the case data (deterministic, no LLM call)."""
    case, share = load_case(session, principal, case_id)
    if not policy.can_edit_case(principal, case, share):
        raise forbidden()
    _require_writable_report(case, report_service.get_report(session, case_id))
    report = report_service.get_or_create_report(session, case_id)
    content = report_service.build_draft_content(session, settings, case)
    version = report_service.add_version(session, settings, report, content, principal.id)
    audit.record(
        session, audit.REPORT_GENERATE, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case_id, detail={"version": version.version},
    )  # fmt: skip
    session.commit()
    return _report_out(session, settings, report, version)


@router.put("/cases/{case_id}/report", response_model=ReportOut)
def edit_report(
    case_id: uuid.UUID,
    request: Request,
    body: ReportEdit,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ReportOut:
    """Attorney or analyst edit: stored as a new version, earlier versions stay intact."""
    case, share = load_case(session, principal, case_id)
    if not policy.can_edit_case(principal, case, share):
        raise forbidden()
    report = report_service.get_report(session, case_id)
    if report is None or report.current_version == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Generate a report first")
    _require_writable_report(case, report)
    content = dict(body.content)
    # The legal disclaimer is part of every version and cannot be edited away.
    content["disclaimer"] = report_service.DISCLAIMER
    if len(json.dumps(content, ensure_ascii=False)) > MAX_REPORT_CHARS:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Report is too large")
    version = report_service.add_version(session, settings, report, content, principal.id)
    audit.record(
        session, audit.REPORT_EDIT, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case_id, detail={"version": version.version},
    )  # fmt: skip
    session.commit()
    return _report_out(session, settings, report, version)


@router.get("/cases/{case_id}/report", response_model=ReportOut)
def get_report(
    case_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    version: int | None = Query(default=None, ge=1),
) -> ReportOut:
    load_case(session, principal, case_id)
    report = _require_report(session, case_id)
    row = report_service.get_version(session, report, version)
    if row is None:
        raise not_found()
    return _report_out(session, settings, report, row)


@router.post("/cases/{case_id}/report/export")
def export_report(
    case_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    format: str = Query(default="json", pattern="^(json|pdf)$"),
) -> Response:
    case, share = load_case(session, principal, case_id)
    if not policy.can_export_case(principal, case, share):
        raise forbidden()
    if format == "pdf":
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "PDF export is delivered with the pipeline in Phase 5"
        )
    report = _require_report(session, case_id)
    version = report_service.get_version(session, report)
    payload = {
        "case_id": str(case.id),
        "title": case.title,
        "state": report.state,
        "version": version.version,
        "content_hash": version.content_hash,
        "approval": _approval(session, version),
        "content": report_service.read_content(settings, version),
        "exported_at": datetime.now(UTC).isoformat(),
    }
    audit.record(
        session, audit.EXPORT, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case_id, detail={"format": "json", "version": version.version},
    )  # fmt: skip
    session.commit()
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="report-{case.id}-v{version.version}.json"'
        },
    )


# ---- review -------------------------------------------------------------------


@router.post("/cases/{case_id}/review/submit", response_model=ReportOut)
def submit_for_review(
    case_id: uuid.UUID,
    request: Request,
    body: ReviewComment,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ReportOut:
    case, share = load_case(session, principal, case_id)
    if not policy.can_submit_for_review(principal, case, share):
        raise forbidden()
    if case.status not in ("draft", "changes_requested"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A {case.status} case cannot be submitted")
    report = report_service.get_report(session, case_id)
    if report is None or report.current_version == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Generate a report first")
    case.status = "in_review"
    report.state = "in_review"
    session.add(_event(case_id, principal.id, "submitted", body.comment))
    audit.record(
        session, audit.REVIEW_SUBMIT, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case_id, detail={"version": report.current_version},
    )  # fmt: skip
    session.commit()
    return _report_out(session, settings, report, report_service.get_version(session, report))


@router.post("/cases/{case_id}/review/approve", response_model=ReportOut)
def approve(
    case_id: uuid.UUID,
    request: Request,
    body: ReviewComment,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ReportOut:
    """Attorney sign-off. Freezes the current version with a stamp and locks the case."""
    case, share = load_case(session, principal, case_id)
    if not policy.can_review_case(principal, case, share):
        raise forbidden()
    report = report_service.get_report(session, case_id)
    if case.status != "in_review" or report is None or report.state != "in_review":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a report in review can be approved")
    version = report_service.get_version(session, report)
    version.approved_by = principal.id
    version.approved_at = datetime.now(UTC)
    report.state = "approved"
    case.status = "approved"
    session.add(_event(case_id, principal.id, "approved", body.comment))
    audit.record(
        session, audit.APPROVE, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case_id,
        detail={"version": version.version, "content_hash": version.content_hash},
    )  # fmt: skip
    session.commit()
    return _report_out(session, settings, report, version)


@router.post("/cases/{case_id}/review/request-changes", response_model=ReportOut)
def request_changes(
    case_id: uuid.UUID,
    request: Request,
    body: ChangesRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ReportOut:
    case, share = load_case(session, principal, case_id)
    if not policy.can_review_case(principal, case, share):
        raise forbidden()
    report = report_service.get_report(session, case_id)
    if case.status != "in_review" or report is None or report.state != "in_review":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a report in review can be sent back")
    case.status = "changes_requested"
    report.state = "changes_requested"
    session.add(_event(case_id, principal.id, "changes_requested", body.comment))
    audit.record(
        session, audit.REQUEST_CHANGES, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case_id,
    )  # fmt: skip
    session.commit()
    return _report_out(session, settings, report, report_service.get_version(session, report))


@router.get("/cases/{case_id}/review", response_model=list[ReviewEventOut])
def review_events(
    case_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[ReviewEventOut]:
    load_case(session, principal, case_id)
    rows = session.scalars(
        select(ReviewEvent).where(ReviewEvent.case_id == case_id).order_by(ReviewEvent.id)
    ).all()
    return [
        ReviewEventOut(
            id=r.id, event_type=r.event_type, user_id=r.user_id, cell_id=r.cell_id,
            comment=r.comment, created_at=r.created_at,
        )
        for r in rows
    ]  # fmt: skip
