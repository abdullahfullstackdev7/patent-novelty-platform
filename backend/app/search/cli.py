"""Run a search from a disclosure JSON file.

python -m app.search.cli ../dataset/disclosures/federated_learning_imaging.json --explain
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from app.db.session import make_engine, make_session_factory
from app.search.embedding import CrossEncoderReranker, SentenceTransformerEmbedder
from app.search.schemas import DisclosureQuery
from app.search.service import SearchService


def load_disclosure(path: Path, **overrides: object) -> DisclosureQuery:
    data = json.loads(path.read_text(encoding="utf-8"))
    elements = [item["text"] if isinstance(item, dict) else str(item) for item in data["elements"]]
    summary = " ".join(part for part in (data.get("problem"), data.get("solution")) if part)
    return DisclosureQuery(
        title=data["title"],
        summary=summary,
        elements=elements,
        priority_date=date.fromisoformat(data["priority_date"]),
        cpc_prefix=overrides.get("cpc_prefix") or data.get("cpc_prefix"),
        sources=overrides.get("sources"),
    )


def build_service(use_reranker: bool = True) -> SearchService:
    factory = make_session_factory(make_engine())
    reranker = CrossEncoderReranker() if use_reranker else None
    return SearchService(factory, SentenceTransformerEmbedder(), reranker)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("disclosure", type=Path)
    parser.add_argument("--cpc-prefix")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--explain", action="store_true", help="print the vector query plan")
    args = parser.parse_args()

    query = load_disclosure(args.disclosure, cpc_prefix=args.cpc_prefix)
    service = build_service(use_reranker=not args.no_rerank)
    response = service.search(query)

    for rank, hit in enumerate(response.hits, start=1):
        print(f"{rank:>2}. {hit.score:8.3f}  {hit.patent_id:<18} {hit.source:<8} {hit.title[:70]}")
        for match in hit.matched_chunks[:1]:
            print(f"      [{match.chunk_type}] {match.text[:110]}")
    print("suggested CPC:", ", ".join(f"{c.subclass} ({c.votes})" for c in response.suggested_cpc))
    print("timings ms:", {key: round(value, 1) for key, value in response.timings_ms.items()})
    if args.explain:
        print("\nPlan (default):\n" + service.explain_vector_query(query))
        print(
            "\nPlan (seqscan disabled):\n"
            + service.explain_vector_query(query, disable_seqscan=True)
        )


if __name__ == "__main__":
    main()
