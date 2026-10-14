"""Job queue: claim order, SKIP LOCKED, retries with backoff, stuck-job recovery, worker handler."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.db.models import Job
from app.pipeline import queue
from app.pipeline.runner import RunOptions
from app.worker import make_job_handler

NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture(autouse=True)
def clean_jobs(engine, clean_db):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs"))


def add_job(session_factory, *, created_offset=0, status="queued", run_after=None, case_id=None,
            locked_at=None, kind="pipeline", attempts=0) -> uuid.UUID:  # fmt: skip
    with session_factory() as session:
        job = Job(case_id=case_id, kind=kind, status=status, attempts=attempts, locked_at=locked_at,
                  locked_by="old-worker" if locked_at else None,
                  payload={"options": {"references": 2}},
                  created_at=NOW + timedelta(seconds=created_offset),
                  run_after=run_after or NOW - timedelta(days=1))  # fmt: skip
        session.add(job)
        session.commit()
        return job.id


def job_row(session_factory, job_id):
    with session_factory() as session:
        return session.get(Job, job_id)


def test_oldest_due_job_is_claimed_and_marked_running(session_factory):
    newer = add_job(session_factory, created_offset=10)
    older = add_job(session_factory, created_offset=1)
    claimed = queue.claim_next_job(session_factory, "w1", now=NOW)
    assert claimed.id == older and claimed.attempts == 1 and claimed.kind == "pipeline"
    assert claimed.payload == {"options": {"references": 2}}
    row = job_row(session_factory, older)
    assert (row.status, row.locked_by, row.attempts) == ("running", "w1", 1) and row.locked_at
    assert queue.claim_next_job(session_factory, "w1", now=NOW).id == newer
    assert queue.claim_next_job(session_factory, "w1", now=NOW) is None  # queue is empty


def test_jobs_scheduled_for_later_and_non_queued_jobs_are_not_claimed(session_factory):
    later = add_job(session_factory, run_after=NOW + timedelta(minutes=5))
    add_job(session_factory, status="succeeded")
    add_job(session_factory, status="failed")
    add_job(session_factory, status="running", locked_at=NOW)
    assert queue.claim_next_job(session_factory, "w", now=NOW) is None
    assert queue.claim_next_job(session_factory, "w", now=NOW + timedelta(minutes=6)).id == later


def test_a_locked_job_is_skipped_not_waited_for(session_factory):
    """FOR UPDATE SKIP LOCKED: while one transaction holds the oldest job, another gets the next."""
    first = add_job(session_factory, created_offset=1)
    second = add_job(session_factory, created_offset=2)
    holder = session_factory()
    try:
        holder.execute(select(Job).where(Job.id == first).with_for_update())  # lock held, no commit
        claimed = queue.claim_next_job(session_factory, "w", now=NOW)
        assert claimed.id == second  # returned at once instead of blocking on the locked row
    finally:
        holder.rollback()
        holder.close()
    assert queue.claim_next_job(session_factory, "w", now=NOW).id == first  # free again


def test_concurrent_workers_never_claim_the_same_job(session_factory):
    ids = {add_job(session_factory, created_offset=i) for i in range(24)}
    claimed: list[uuid.UUID] = []
    guard = threading.Lock()

    def worker(name: str) -> None:
        while (job := queue.claim_next_job(session_factory, name, now=NOW)) is not None:
            with guard:
                claimed.append(job.id)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(claimed) == len(set(claimed)) == 24 and set(claimed) == ids


def test_failure_schedules_a_retry_with_exponential_backoff_then_fails_for_good(
    session_factory, settings, users
):
    from pipeline_support import make_case

    case_id = make_case(session_factory, settings, users["attorney"].id)
    job_id = add_job(session_factory, case_id=case_id)
    clock = NOW
    for attempt, delay in ((1, 10), (2, 20)):  # 5 s x 2^attempt
        claimed = queue.claim_next_job(session_factory, "w", now=clock)
        assert claimed.attempts == attempt
        assert (
            queue.mark_failed(session_factory, settings, claimed, RuntimeError("boom"), now=clock)
            is False
        )
        row = job_row(session_factory, job_id)
        assert row.status == "queued" and row.run_after == clock + timedelta(seconds=delay)
        assert row.error.startswith("RuntimeError: boom") and row.locked_by is None
        assert queue.claim_next_job(session_factory, "w", now=clock) is None  # still backing off
        with session_factory() as session:
            assert session.execute(text("SELECT stage FROM cases")).scalar_one() == "retrying"
        clock += timedelta(seconds=delay + 1)

    claimed = queue.claim_next_job(session_factory, "w", now=clock)
    assert claimed.attempts == 3  # JOB_MAX_ATTEMPTS
    assert (
        queue.mark_failed(session_factory, settings, claimed, RuntimeError("last"), now=clock)
        is True
    )
    assert job_row(session_factory, job_id).status == "failed"
    with session_factory() as session:
        row = session.execute(text("SELECT status, stage FROM cases")).one()
    assert (row.status, row.stage) == ("draft", "failed")  # the case is usable again


def test_permanent_errors_fail_immediately(session_factory, settings):
    job_id = add_job(session_factory)
    claimed = queue.claim_next_job(session_factory, "w", now=NOW)
    assert queue.mark_failed(
        session_factory, settings, claimed, queue.PermanentError("no elements"), now=NOW
    )
    row = job_row(session_factory, job_id)
    assert row.status == "failed" and "PermanentError: no elements" in row.error


def test_stored_errors_are_redacted_and_truncated(session_factory, settings):
    job_id = add_job(session_factory)
    claimed = queue.claim_next_job(session_factory, "w", now=NOW)
    nasty = RuntimeError("login failed password=Sup3rSecretValue " + "x" * 1000)
    queue.mark_failed(session_factory, settings, claimed, nasty, now=NOW)
    error = job_row(session_factory, job_id).error
    assert "Sup3rSecretValue" not in error and "[REDACTED]" in error and len(error) <= 300


def test_jobs_of_a_crashed_worker_return_to_the_queue(session_factory, settings):
    stuck = add_job(session_factory, status="running", locked_at=NOW - timedelta(minutes=20))
    busy = add_job(session_factory, status="running", locked_at=NOW - timedelta(minutes=1))
    assert queue.reclaim_stuck(session_factory, settings, now=NOW) == 1
    assert job_row(session_factory, stuck).status == "queued"
    assert job_row(session_factory, stuck).locked_by is None
    assert job_row(session_factory, busy).status == "running"
    assert queue.reclaim_stuck(session_factory, settings, now=NOW) == 0


def test_process_one_runs_the_handler_and_records_the_outcome(session_factory, settings):
    ok, bad = add_job(session_factory, created_offset=1), add_job(session_factory, created_offset=2)
    seen = []

    def handler(job):
        seen.append(job.id)
        if job.id == bad:
            raise ValueError("handler failed")

    assert queue.process_one(session_factory, settings, handler, "w") is True
    assert queue.process_one(session_factory, settings, handler, "w") is True
    assert queue.process_one(session_factory, settings, handler, "w") is False  # nothing due
    assert seen == [ok, bad]
    assert job_row(session_factory, ok).status == "succeeded"
    failed = job_row(session_factory, bad)
    assert failed.status == "queued" and "ValueError" in failed.error  # first failure: will retry


def test_worker_handler_passes_the_payload_options_to_the_runner(settings):
    calls = []
    runner = SimpleNamespace(run=lambda case_id, options: calls.append((case_id, options)) or SimpleNamespace(
        references=["a"], cells_total=3, cells_reused=0, tokens=10, risk_level="low"))  # fmt: skip
    handle = make_job_handler(runner, settings)
    case_id = uuid.uuid4()
    handle(
        queue.ClaimedJob(
            uuid.uuid4(),
            case_id,
            "pipeline",
            {"options": {"references": 2, "force_search": True}},
            1,
        )
    )
    assert calls[0][0] == case_id
    assert isinstance(calls[0][1], RunOptions) and (
        calls[0][1].references,
        calls[0][1].force_search,
    ) == (2, True)
    with pytest.raises(queue.PermanentError, match="unsupported"):
        handle(queue.ClaimedJob(uuid.uuid4(), case_id, "mystery", {}, 1))
    with pytest.raises(queue.PermanentError):
        handle(queue.ClaimedJob(uuid.uuid4(), None, "pipeline", {}, 1))
