"""Search evaluation: do examiner-cited references appear in the top K for claim 1 as the query?

    uv run --project backend python scripts/evaluate_search.py \
        --citations dataset/raw/patentsview/g_us_patent_citation.tsv.zip --limit 200

Needs the corpus loaded with embeddings, granted patents (source PV_GRANT) and the PatentsView
citation file (download with scripts/download_patentsview.py --citations). Prints the results and
replaces the section between the markers in docs/evaluation.md.
"""

from __future__ import annotations

import argparse
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db.models import Patent, PatentClaim  # noqa: E402
from app.db.session import make_engine, make_session_factory  # noqa: E402
from app.search.cli import build_service  # noqa: E402
from app.search.evaluation import (  # noqa: E402
    KS,
    evaluate,
    load_examiner_citations,
    normalize_patent_number,
    pick_cases,
)
from app.search.schemas import DisclosureQuery  # noqa: E402

START, END = "<!-- search-eval:start -->", "<!-- search-eval:end -->"


def open_citations(path: Path) -> Path:
    """Unzip the citation file next to the archive once and return the TSV path."""
    if path.suffix != ".zip":
        return path
    target = path.with_suffix("")
    if not target.exists():
        with zipfile.ZipFile(path) as archive:
            name = archive.namelist()[0]
            archive.extract(name, target.parent)
            (target.parent / name).rename(target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--citations", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "evaluation.md")
    args = parser.parse_args()

    sessions = make_session_factory(make_engine())
    with sessions() as session:
        granted = session.execute(
            select(Patent.id, Patent.title, Patent.abstract, Patent.publication_date).where(
                Patent.source == "PV_GRANT"
            )
        ).all()
        claims = dict(
            session.execute(
                select(PatentClaim.patent_id, PatentClaim.text).where(PatentClaim.number == 1)
            ).all()
        )
        numbers = {pid: normalize_patent_number(pid) for pid in session.scalars(select(Patent.id))}
    if not granted:
        sys.exit("The corpus has no granted patents (source PV_GRANT), so there is nothing to evaluate.")

    citations = load_examiner_citations(open_citations(args.citations))
    pool = {pid: numbers[pid] for pid, *_ in granted if pid in claims}
    cases = pick_cases({**numbers, **pool}, citations, args.limit)
    cases = [(pid, rel) for pid, rel in cases if pid in pool]
    if not cases:
        sys.exit("None of the granted patents has an examiner-cited reference inside the corpus.")
    info = {pid: (title, abstract, published) for pid, title, abstract, published in granted}

    service = build_service(use_reranker=not args.no_rerank)

    def search(pid: str) -> list[str]:
        title, abstract, published = info[pid]
        query = DisclosureQuery(
            title=title or "",
            summary=abstract or "",
            elements=[claims[pid]],
            priority_date=published or date.today(),
        )
        return [hit.patent_id for hit in service.search(query).hits]

    started = time.time()
    summary = evaluate(cases, search, KS)
    stamp = f"Measured {date.today()} on {summary.queries} granted patents in {time.time() - started:.0f} s."
    section = f"{START}\n{summary.as_markdown()}\n\n{stamp}\n{END}"
    print(section)
    if args.out.exists():
        text = args.out.read_text(encoding="utf-8")
        if START in text and END in text:
            text = text[: text.index(START)] + section + text[text.index(END) + len(END) :]
            args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
