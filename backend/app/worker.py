"""Pipeline worker: claims queued jobs from Postgres and runs the analysis pipeline.

    uv run python -m app.worker

Several workers can run side by side, the queue uses FOR UPDATE SKIP LOCKED. A job whose worker
died is put back after JOB_STUCK_MINUTES and resumes, because every stage is idempotent.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.billing import periodic
from app.config import Settings, get_settings
from app.db.session import make_engine, make_session_factory
from app.llm.factory import build_gateway
from app.pipeline import queue
from app.pipeline.runner import PipelineRunner, RunOptions
from app.security.redaction import install_log_redaction

logger = logging.getLogger("priorart.worker")
RECLAIM_EVERY_SECONDS = 60


def make_job_handler(runner: PipelineRunner, settings: Settings):
    def handle(job: queue.ClaimedJob) -> None:
        if job.kind != "pipeline" or job.case_id is None:
            raise queue.PermanentError(f"unsupported job kind {job.kind}")
        options = RunOptions.from_payload(job.payload, settings.pipeline_references)
        summary = runner.run(job.case_id, options)
        logger.info(
            "case %s done: %d references, %d cells (%d reused), %d tokens, risk %s",
            job.case_id, len(summary.references), summary.cells_total, summary.cells_reused,
            summary.tokens, summary.risk_level,
        )  # fmt: skip

    return handle


def build_runner(settings: Settings, sessions: sessionmaker[Session]) -> PipelineRunner:
    # The model classes are imported here: they load torch, which the API process never needs.
    from app.search.embedding import CrossEncoderReranker, SentenceTransformerEmbedder

    return PipelineRunner(
        sessions,
        settings,
        build_gateway(settings, sessions),
        SentenceTransformerEmbedder(settings, batch_size=16, max_seq_length=256),
        CrossEncoderReranker(settings),
    )


def run_forever(
    sessions: sessionmaker[Session],
    settings: Settings,
    handler,
    stop: threading.Event,
    worker_id: str,
) -> None:
    last_reclaim = 0.0
    while not stop.is_set():
        if time.monotonic() - last_reclaim > RECLAIM_EVERY_SECONDS:
            reclaimed = queue.reclaim_stuck(sessions, settings)
            if reclaimed:
                logger.warning("returned %d stuck job(s) to the queue", reclaimed)
            try:
                done = periodic.run_due(sessions, settings)
                if done:
                    logger.info("billing cycle: %s", done)
            except Exception:  # a billing problem must never stop the analysis worker
                logger.exception("billing cycle failed")
            last_reclaim = time.monotonic()
        if not queue.process_one(sessions, settings, handler, worker_id):
            stop.wait(settings.job_poll_seconds)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    install_log_redaction()
    settings = get_settings()
    settings.validate_runtime()
    sessions = make_session_factory(make_engine(settings.database_url))
    runner = build_runner(settings, sessions)
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        signal.signal(getattr(signal, name), lambda *_: stop.set())
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    logger.info("worker %s started", worker_id)
    run_forever(sessions, settings, make_job_handler(runner, settings), stop, worker_id)
    logger.info("worker %s stopped", worker_id)


if __name__ == "__main__":
    main()
