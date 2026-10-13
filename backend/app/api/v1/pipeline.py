"""Pipeline endpoints: queue a run, stream progress, read results and the claim chart."""

# No `from __future__ import annotations` here: slowapi wraps the endpoints and FastAPI would
# then fail to resolve the string annotations against the wrapper's globals.
import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.api.deps import PrincipalDep, SessionDep, SettingsDep, ip_of
from app.api.v1.cases import ensure_editable
from app.api.v1.schemas import (
    CellOut,
    CellOverride,
    ChartOut,
    ElementOut,
    JobOut,
    ResultOut,
    ResultsOut,
)
from app.db.models import (
    Case,
    ChartCell,
    ClaimChart,
    DisclosureElement,
    Job,
    LlmCall,
    Patent,
    ReviewEvent,
    SearchResult,
    SearchRun,
)
from app.security import policy
from app.security.http import limiter, llm_limit
from app.services import audit
from app.services.access import forbidden, load_case, not_found
from app.services.disclosures import load_disclosure

router = APIRouter(tags=["pipeline"])

ACTIVE_JOB_STATES = ("queued", "running")
TERMINAL_JOB_STATES = ("succeeded", "failed", "cancelled")
STREAM_POLL_SECONDS = 1.0
STREAM_MAX_SECONDS = 1800
HEARTBEAT_EVERY = 15


def _job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id, kind=job.kind, status=job.status, attempts=job.attempts, error=job.error,
        created_at=job.created_at, updated_at=job.updated_at,
    )  # fmt: skip


@router.post("/cases/{case_id}/run", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(llm_limit)
def run_case(
    request: Request,
    case_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> JobOut:
    """Queue the analysis pipeline. The worker (Phase 5) picks the job up with SKIP LOCKED."""
    case, share = load_case(session, principal, case_id)
    if not policy.can_run_case(principal, case, share):
        raise forbidden()
    ensure_editable(case)
    disclosure = load_disclosure(session, settings, case_id)
    if disclosure is None or not disclosure.elements:
        raise HTTPException(status.HTTP_409_CONFLICT, "Add a disclosure with elements first")
    active = session.scalar(
        select(Job.id).where(Job.case_id == case_id, Job.status.in_(ACTIVE_JOB_STATES))
    )
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A run is already queued or in progress")
    job = Job(case_id=case_id, kind="pipeline", status="queued", payload={"case_id": str(case_id)})
    session.add(job)
    case.status = "running"
    case.stage = "queued"
    case.updated_at = datetime.now(UTC)
    session.flush()
    audit.record(
        session, audit.CASE_RUN, user_id=principal.id, ip=ip_of(request),
        entity_type="case", entity_id=case_id, detail={"job_id": str(job.id)},
    )  # fmt: skip
    session.commit()
    session.refresh(job)
    return _job_out(job)


def _snapshot(factory: sessionmaker[Session], case_id: uuid.UUID) -> dict[str, Any]:
    with factory() as session:
        case = session.get(Case, case_id)
        job = session.scalar(
            select(Job).where(Job.case_id == case_id).order_by(Job.created_at.desc()).limit(1)
        )
        tokens = session.scalar(
            select(func.coalesce(func.sum(LlmCall.tokens_in + LlmCall.tokens_out), 0)).where(
                LlmCall.case_id == case_id
            )
        )
        if case is None:
            return {"status": "deleted"}
        return {
            "status": job.status if job else "idle",
            "job_id": str(job.id) if job else None,
            "stage": case.stage,
            "case_status": case.status,
            "attempts": job.attempts if job else 0,
            "error": job.error if job else None,
            "tokens_used": int(tokens or 0),
            "updated_at": (job.updated_at if job else case.updated_at).isoformat(),
        }


async def _events(
    factory: sessionmaker[Session], case_id: uuid.UUID, once: bool
) -> AsyncIterator[str]:
    previous: dict[str, Any] | None = None
    quiet = 0
    waited = 0.0
    while True:
        snapshot = await run_in_threadpool(_snapshot, factory, case_id)
        if snapshot != previous:
            previous, quiet = snapshot, 0
            yield f"event: status\ndata: {json.dumps(snapshot)}\n\n"
        else:
            quiet += 1
            if quiet % HEARTBEAT_EVERY == 0:
                yield ": keep-alive\n\n"
        if once or snapshot["status"] in (*TERMINAL_JOB_STATES, "idle", "deleted"):
            return
        waited += STREAM_POLL_SECONDS
        if waited >= STREAM_MAX_SECONDS:
            return
        await asyncio.sleep(STREAM_POLL_SECONDS)


@router.get("/cases/{case_id}/progress")
def progress(
    request: Request,
    case_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    once: bool = Query(default=False, description="Send one snapshot and close the stream"),
) -> StreamingResponse:
    """Server-Sent Events with the job status. Ends when the job reaches a final state."""
    load_case(session, principal, case_id)
    return StreamingResponse(
        _events(request.app.state.session_factory, case_id, once),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/cases/{case_id}/results", response_model=ResultsOut)
def results(case_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> ResultsOut:
    load_case(session, principal, case_id)
    run = session.scalar(
        select(SearchRun).where(SearchRun.case_id == case_id).order_by(SearchRun.created_at.desc())
    )
    if run is None:
        return ResultsOut(run_id=None, suggested_cpc=[], results=[])
    rows = session.execute(
        select(SearchResult, Patent)
        .join(Patent, Patent.id == SearchResult.patent_id, isouter=True)
        .where(SearchResult.run_id == run.id)
        .order_by(SearchResult.rank)
    ).all()
    return ResultsOut(
        run_id=run.id,
        suggested_cpc=run.suggested_cpc,
        results=[
            ResultOut(
                rank=r.rank, patent_id=r.patent_id,
                title=p.title if p else None, source=p.source if p else None,
                assignee=p.assignee if p else None,
                publication_date=p.publication_date if p else None,
                cpc_subclasses=list(p.cpc_subclasses) if p else [],
                url=p.url if p else None, score=r.score, fused_score=r.fused_score,
                rerank_score=r.rerank_score, matched_chunk_ids=list(r.matched_chunk_ids),
                excluded=r.excluded, in_chart=r.in_chart,
            )
            for r, p in rows
        ],
    )  # fmt: skip


def _cell_out(cell: ChartCell, key: str) -> CellOut:
    return CellOut(
        id=cell.id, element=key, patent_id=cell.patent_id, status=cell.status,
        confidence=float(cell.confidence), passage_id=cell.passage_id, excerpt=cell.excerpt,
        rationale=cell.rationale, method=cell.method, overridden=cell.overridden_at is not None,
        original=cell.original, override_reason=cell.override_reason,
    )  # fmt: skip


@router.get("/cases/{case_id}/chart", response_model=ChartOut)
def chart(
    case_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> ChartOut:
    load_case(session, principal, case_id)
    disclosure = load_disclosure(session, settings, case_id)
    elements = [
        ElementOut(id=e.key, position=e.position, text=e.text, source=e.source)
        for e in (disclosure.elements if disclosure else [])
    ]
    claim_chart = session.scalar(select(ClaimChart).where(ClaimChart.case_id == case_id))
    if claim_chart is None:
        return ChartOut(chart_status=None, elements=elements, references=[], cells=[])
    keys = {
        e.id: e.key
        for e in session.scalars(
            select(DisclosureElement).where(
                DisclosureElement.id.in_(
                    select(ChartCell.element_id).where(ChartCell.chart_id == claim_chart.id)
                )
            )
        )
    }
    cells = session.scalars(
        select(ChartCell).where(ChartCell.chart_id == claim_chart.id).order_by(ChartCell.patent_id)
    ).all()
    return ChartOut(
        chart_status=claim_chart.status,
        elements=elements,
        references=sorted({c.patent_id for c in cells}),
        cells=[_cell_out(c, keys.get(c.element_id, "")) for c in cells],
    )


@router.patch("/chart/cells/{cell_id}", response_model=CellOut)
def override_cell(
    cell_id: uuid.UUID,
    request: Request,
    body: CellOverride,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> CellOut:
    """Attorney override of a chart cell. The first original value is kept for the audit trail."""
    cell = session.get(ChartCell, cell_id)
    claim_chart = session.get(ClaimChart, cell.chart_id) if cell else None
    if cell is None or claim_chart is None:
        raise not_found()
    case, share = load_case(session, principal, claim_chart.case_id)
    if not policy.can_review_case(principal, case, share):
        raise forbidden()
    ensure_editable(case)
    previous = cell.status
    if cell.original is None:
        cell.original = {
            "status": cell.status, "method": cell.method, "confidence": float(cell.confidence),
            "excerpt": cell.excerpt, "rationale": cell.rationale,
        }  # fmt: skip
    cell.status = body.status
    cell.override_reason = body.reason
    cell.overridden_by = principal.id
    cell.overridden_at = datetime.now(UTC)
    cell.updated_at = datetime.now(UTC)
    session.add(
        ReviewEvent(
            case_id=case.id, user_id=principal.id, cell_id=cell.id,
            event_type="cell_override", comment=body.reason,
        )
    )  # fmt: skip
    audit.record(
        session, audit.CELL_OVERRIDE, user_id=principal.id, ip=ip_of(request),
        entity_type="chart_cell", entity_id=cell.id,
        detail={"case_id": str(case.id), "from": previous, "to": body.status},
    )  # fmt: skip
    session.commit()
    element = session.get(DisclosureElement, cell.element_id)
    return _cell_out(cell, element.key if element else "")
