"""Validate corpus.parquet and chunks.parquet and print a random spot-check sample.

    python scripts/validate_corpus.py [--dir dataset/processed] [--sample 20] [--seed 13]

Exit code is non-zero if any integrity check fails. The spot-check report is written to
<dir>/spot_check.md so claim parsing can be reviewed by hand against the source patents.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from _common import PROCESSED


def check(corpus: pd.DataFrame, chunks: pd.DataFrame) -> list[str]:
    problems: list[str] = []
    dupes = int(corpus["patent_id"].duplicated().sum())
    if dupes:
        problems.append(f"{dupes} duplicate patent_id values in corpus")
    if chunks["chunk_id"].duplicated().any():
        problems.append("duplicate chunk_id values")
    orphans = ~chunks["patent_id"].isin(corpus["patent_id"])
    if orphans.any():
        problems.append(f"{int(orphans.sum())} chunks reference unknown patents")
    claims = chunks[chunks["chunk_type"] == "claim"]
    with_claims = set(claims["patent_id"])
    missing = set(corpus["patent_id"]) - with_claims
    if missing:
        problems.append(f"{len(missing)} patents have no claim chunks")
    for column in ("title", "publication_date", "source"):
        empty = int((corpus[column].isna() | (corpus[column] == "")).sum())
        if empty:
            problems.append(f"{empty} patents with empty {column}")
    # claim numbers must strictly increase (gaps are allowed: canceled claims are dropped)
    ordered = claims.sort_values(["patent_id", "seq"])
    steps = ordered.groupby("patent_id")["claim_number"].diff().dropna()
    if (steps <= 0).any():
        problems.append(f"{int((steps <= 0).sum())} claims out of order or repeated")
    canceled = claims[claims["text"].str.fullmatch(r"\(?\s*(?i:cancell?ed)\s*\)?\.?")]
    if len(canceled):
        problems.append(f"{len(canceled)} canceled claims kept as claims")
    dependents = claims[~claims["is_independent"].astype(bool)]
    forward = dependents[dependents["parent_claim"] >= dependents["claim_number"]]
    if len(forward):
        problems.append(f"{len(forward)} dependent claims reference a later claim")
    no_independent = set(corpus["patent_id"]) - set(claims[claims["is_independent"]]["patent_id"])
    if no_independent:
        problems.append(f"{len(no_independent)} patents without an independent claim")
    mismatch = claims[claims["char_end"] - claims["char_start"] != claims["text"].str.len()]
    if len(mismatch):
        problems.append(f"{len(mismatch)} claim chunks with inconsistent offsets")
    return problems


def spot_check(corpus: pd.DataFrame, chunks: pd.DataFrame, n: int, seed: int) -> str:
    lines = [f"# Corpus spot check ({n} random patents, seed {seed})", ""]
    for _, row in corpus.sample(n=min(n, len(corpus)), random_state=seed).iterrows():
        claims = chunks[
            (chunks["patent_id"] == row["patent_id"]) & (chunks["chunk_type"] == "claim")
        ].sort_values("claim_number")
        lines += [
            f"## {row['patent_id']} ({row['source']}): {row['title']}",
            f"CPC {', '.join(row['cpc_codes'][:4])} | published {row['publication_date']} | "
            f"{row['n_claims']} claims, {row['n_independent']} independent",
            "",
        ]
        for claim in claims.itertuples():
            kind = (
                "independent" if claim.is_independent else f"dependent on {int(claim.parent_claim)}"
            )
            text = claim.text if len(claim.text) <= 140 else claim.text[:140] + " ..."
            lines.append(f"- claim {int(claim.claim_number)} ({kind}): {text}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=PROCESSED)
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    corpus = pd.read_parquet(args.dir / "corpus.parquet")
    chunks = pd.read_parquet(args.dir / "chunks.parquet")
    print(f"patents: {len(corpus):,}")
    print(f"chunks:  {len(chunks):,}")
    print(chunks["chunk_type"].value_counts().to_string())
    print("by source:", corpus["source"].value_counts().to_dict())
    words = chunks[chunks["chunk_type"].isin(["summary", "description"])]["n_words"]
    print(f"passage words min/median/max: {words.min()}/{words.median():.0f}/{words.max()}")

    problems = check(corpus, chunks)
    report = spot_check(corpus, chunks, args.sample, args.seed)
    (args.dir / "spot_check.md").write_text(report, encoding="utf-8")
    print(f"spot check written to {args.dir / 'spot_check.md'}")
    for problem in problems:
        print("FAIL:", problem, file=sys.stderr)
    print("PASS" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
