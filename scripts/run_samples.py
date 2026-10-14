"""Run the sample disclosures end to end and check the Phase 5 acceptance criteria.

    uv run --project backend python scripts/run_samples.py
    uv run --project backend python scripts/run_samples.py --references 3 --report docs/samples_run.md

Needs the database loaded with the corpus and its embeddings (scripts/quickstart_demo.py or a
full load). The local models run on CPU. Without GROQ_API_KEY or GEMINI_API_KEY the LLM steps
fall back to local rules and the token columns stay at zero, so run with at least one key to
measure the real token cost.

Checks, per disclosure and overall:
  * the pipeline completes and writes a report,
  * every stored excerpt is a verbatim substring of its source chunk,
  * a second run of the identical case uses zero LLM tokens,
  * the median tokens per case is at most 9,000 (p95 at most 12,000).
Test cases are removed afterwards unless --keep is given.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select, text

from app.config import get_settings
from app.db.models import Case, Role, User
from app.db.session import make_engine, make_session_factory
from app.pipeline import classify
from app.pipeline.runner import RunOptions
from app.services.disclosures import save_disclosure
from app.worker import build_runner

ROOT = Path(__file__).resolve().parent.parent
OWNER_EMAIL = "sample-runner@localhost.invalid"
MEDIAN_LIMIT, P95_LIMIT = 9000, 12000


def owner_id(sessions) -> object:
    """A passwordless system user that owns the sample cases (it cannot log in)."""
    with sessions() as session:
        user = session.scalar(select(User).where(User.email == OWNER_EMAIL))
        if user is None:
            role = session.scalar(select(Role.id).where(Role.name == "analyst"))
            user = User(
                email=OWNER_EMAIL, full_name="Sample runner", role_id=role, password_hash=None
            )
            session.add(user)
            session.commit()
        return user.id


def create_case(sessions, settings, owner, data: dict) -> object:
    with sessions() as session:
        case = Case(
            owner_id=owner,
            title=f"[sample] {data['title']}",
            priority_date=date.fromisoformat(data["priority_date"]),
            status="running",
        )
        session.add(case)
        session.flush()
        save_disclosure(
            session, settings, case.id,
            title=data["title"], technical_field=data["technical_field"],
            problem=data["problem"], solution=data["solution"],
            elements=[(e["text"], "user") for e in data["elements"]],
        )  # fmt: skip
        session.commit()
        return case.id


def verify_excerpts(sessions, case_id) -> tuple[int, int]:
    """(verified, total) excerpts of the case, compared with the source chunk text."""
    verified = total = 0
    with sessions() as session:
        rows = session.execute(
            text(
                "SELECT c.passage_id, c.excerpt, c.char_start, c.char_end FROM chart_cells c "
                "JOIN claim_charts ch ON ch.id = c.chart_id WHERE ch.case_id = :c AND c.excerpt IS NOT NULL"
            ),
            {"c": case_id},
        ).all()
        for passage_id, excerpt, start, end in rows:
            source = session.execute(
                text("SELECT text FROM patent_chunks WHERE id = :i"), {"i": passage_id}
            ).scalar_one_or_none()
            total += 1
            verified += int(
                source is not None and classify.excerpt_is_verbatim(excerpt, source, start, end)
            )
    return verified, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--references", type=int, default=3)
    parser.add_argument("--keep", action="store_true", help="keep the created cases")
    parser.add_argument("--report", type=Path, help="write a markdown report here")
    args = parser.parse_args()

    settings = get_settings()
    sessions = make_session_factory(make_engine(settings.database_url))
    runner = build_runner(settings, sessions)
    owner = owner_id(sessions)
    options = RunOptions(references=args.references)
    rows, failures, created = [], [], []

    for path in sorted((ROOT / "dataset" / "disclosures").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        case_id = create_case(sessions, settings, owner, data)
        created.append(case_id)
        started = time.perf_counter()
        first = runner.run(case_id, options)
        seconds = time.perf_counter() - started
        again = runner.run(case_id, options)
        verified, total = verify_excerpts(sessions, case_id)
        rows.append((path.stem, first, again, verified, total, seconds))
        if verified != total:
            failures.append(f"{path.stem}: {total - verified} excerpt(s) are not verbatim")
        if again.tokens != 0:
            failures.append(f"{path.stem}: rerun used {again.tokens} tokens")

    tokens = sorted(r[1].tokens for r in rows)
    median = statistics.median(tokens)
    p95 = tokens[min(len(tokens) - 1, round(0.95 * (len(tokens) - 1)))]
    if any(r[1].report_version is None for r in rows):
        failures.append("a run finished without a report")
    if median > MEDIAN_LIMIT or p95 > P95_LIMIT:
        failures.append(f"token budget exceeded: median {median}, p95 {p95}")

    lines = [
        "| Disclosure | Refs | Cells | Local | LLM | Fallback | Tokens | Calls | Risk | Score | Rerun tokens | Excerpts | Seconds |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, first, again, verified, total, seconds in rows:
        stats = first.charting
        lines.append(
            f"| {name} | {len(first.references)} | {first.cells_total} | {stats.local_cells} | {stats.llm_cells} "
            f"| {stats.fallback_cells} | {first.tokens} | {first.llm_calls} | {first.risk_level} "
            f"| {first.risk_score} | {again.tokens} | {verified}/{total} | {seconds:.1f} |"
        )
    lines += ["", f"Median tokens per case: {median}. 95th percentile: {p95}. "
                  f"Target: median at most {MEDIAN_LIMIT}.",
              "LLM used: " + ("yes" if any(r[1].llm_used for r in rows) else "no (local fallback only)")]  # fmt: skip
    report = "\n".join(lines)
    print(report)
    if args.report:
        args.report.write_text(report + "\n", encoding="utf-8")

    if not args.keep:
        with sessions() as session:
            session.execute(delete(Case).where(Case.id.in_(created)))
            session.commit()
    for failure in failures:
        print("FAIL:", failure, file=sys.stderr)
    print("PASS" if not failures else f"{len(failures)} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
