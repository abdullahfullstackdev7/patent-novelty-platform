"""Postgres job queue: claim with FOR UPDATE SKIP LOCKED, retry with backoff, reclaim stuck jobs."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Case, Job
from app.security.redaction import redact

logger = logging.getLogger("priorart.worker")
RETRY_BASE_SECONDS = 5
MAX_ERROR_CHARS = 300


class PermanentError(Exception):
    """A failure retrying cannot fix, such as a case without elements. Fails the job at once."""


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    case_id: uuid.UUID | None
    kind: str
    payload: dict
    attempts: int


def _db_now(session: Session) -> datetime:
    """The database clock, so due times do not depend on the host clock."""
    return session.scalar(select(func.now()))


def claim_next_job(
    sessions: sessionmaker[Session], worker_id: str, now: datetime | None = None
) -> ClaimedJob | None:
    """Take the oldest due job. SKIP LOCKED lets several workers claim without blocking."""
    with sessions() as session:
        moment = now or _db_now(session)
        job = session.scalars(
            select(Job)
            .where(Job.status == "queued", Job.run_after <= moment)
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if job is None:
            return None
        job.status = "running"
        job.locked_at = moment
        job.locked_by = worker_id
        job.attempts += 1
        job.updated_at = moment
        session.commit()
        return ClaimedJob(job.id, job.case_id, job.kind, dict(job.payload), job.attempts)


def reclaim_stuck(
    sessions: sessionmaker[Session], settings: Settings, now: datetime | None = None
) -> int:
    """Put jobs of a crashed worker back in the queue. Stages are idempotent, so they resume."""
    with sessions() as session:
        moment = now or _db_now(session)
        cutoff = moment - timedelta(minutes=settings.job_stuck_minutes)
        result = session.execute(
            update(Job)
            .where(Job.status == "running", Job.locked_at < cutoff)
            .values(status="queued", locked_at=None, locked_by=None, updated_at=moment)
        )
        session.commit()
        return result.rowcount or 0


def mark_succeeded(sessions: sessionmaker[Session], job_id: uuid.UUID) -> None:
    with sessions() as session:
        job = session.get(Job, job_id)
        job.status = "succeeded"
        job.error = None
        job.locked_at = job.locked_by = None
        job.updated_at = _db_now(session)
        session.commit()


def mark_failed(
    sessions: sessionmaker[Session],
    settings: Settings,
    job: ClaimedJob,
    error: BaseException,
    now: datetime | None = None,
) -> bool:
    """Record a failure. Returns True when the job is finished for good, False when it will
    be retried after an exponential delay."""
    final = isinstance(error, PermanentError) or job.attempts >= settings.job_max_attempts
    message = f"{type(error).__name__}: {redact(str(error))}"[:MAX_ERROR_CHARS]
    with sessions() as session:
        moment = now or _db_now(session)
        row = session.get(Job, job.id)
        row.error = message
        row.locked_at = row.locked_by = None
        row.updated_at = moment
        if final:
            row.status = "failed"
        else:
            row.status = "queued"
            row.run_after = moment + timedelta(seconds=RETRY_BASE_SECONDS * 2**job.attempts)
        if job.case_id is not None:
            case = session.get(Case, job.case_id)
            if case is not None:
                case.stage = "failed" if final else "retrying"
                if final:
                    case.status = "draft"
        session.commit()
    return final


def process_one(
    sessions: sessionmaker[Session],
    settings: Settings,
    run_job: Callable[[ClaimedJob], None],
    worker_id: str,
) -> bool:
    """Claim and run one job. Returns False when the queue had nothing due."""
    job = claim_next_job(sessions, worker_id)
    if job is None:
        return False
    try:
        run_job(job)
    except Exception as error:
        final = mark_failed(sessions, settings, job, error)
        logger.error(
            "job %s failed (%s, %s)",
            job.id,
            type(error).__name__,
            "final" if final else "will retry",
        )
    else:
        mark_succeeded(sessions, job.id)
    return True
