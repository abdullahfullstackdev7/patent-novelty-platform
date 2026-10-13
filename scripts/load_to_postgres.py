"""Bulk load corpus.parquet, chunks.parquet and embeddings into PostgreSQL with COPY.

    uv run --project backend python scripts/load_to_postgres.py --dir dataset/processed

The heavy indexes (HNSW on the embedding, GIN on the tsvector) are dropped before COPY and
recreated afterwards, which is far faster than maintaining them row by row. By default the
reference tables are truncated first, so the script is safe to rerun. Case history is not
affected because it holds no foreign keys into the corpus. Run `alembic upgrade head` first.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import psycopg
import pyarrow.parquet as pq
from _common import PROCESSED
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.config import EMBEDDING_DIM, get_settings
from app.db.models.reference import HEAVY_INDEX_NAMES, PatentChunk

PATENT_COLUMNS = (
    "id, source, title, abstract, filing_date, publication_date, grant_date, assignee, "
    "cpc_codes, cpc_subclasses, main_subclass, n_claims, n_independent, url"
)
CLAIM_COLUMNS = "patent_id, number, text, is_independent, parent"
CHUNK_COLUMNS = (
    "id, patent_id, type, publication_date, source, claim_number, seq, text, "
    "char_start, char_end, embedding"
)


def psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def heavy_index_ddl() -> dict[str, str]:
    ddl = {}
    for index in PatentChunk.__table__.indexes:
        if index.name in HEAVY_INDEX_NAMES:
            ddl[index.name] = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    return ddl


def load_embeddings(directory: Path) -> tuple[dict[str, int], np.ndarray]:
    ids: list[str] = []
    blocks: list[np.ndarray] = []
    for shard in sorted((directory / "embeddings").glob("part-*.parquet")):
        table = pq.read_table(shard)
        ids.extend(table.column("chunk_id").to_pylist())
        values = table.column("embedding").combine_chunks().values.to_numpy(zero_copy_only=False)
        blocks.append(values.reshape(-1, EMBEDDING_DIM))
    matrix = np.vstack(blocks) if blocks else np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    return {chunk_id: i for i, chunk_id in enumerate(ids)}, matrix


def vector_text(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(x):.6g}" for x in vector) + "]"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=PROCESSED)
    parser.add_argument("--database-url", default=get_settings().database_url)
    parser.add_argument("--append", action="store_true", help="do not truncate first")
    args = parser.parse_args()
    started = time.perf_counter()

    corpus = pq.read_table(args.dir / "corpus.parquet").to_pylist()
    patent_info = {row["patent_id"]: (row["publication_date"], row["source"]) for row in corpus}
    row_index, matrix = load_embeddings(args.dir)
    print(f"{len(corpus):,} patents, {len(row_index):,} embeddings")

    with psycopg.connect(psycopg_url(args.database_url)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.patent_chunks')")
            if cur.fetchone()[0] is None:
                raise SystemExit("patent_chunks is missing: run `alembic upgrade head` first")
            if not args.append:
                cur.execute("TRUNCATE patent_chunks, patent_claims, patents")
            ddl = heavy_index_ddl()
            for name in ddl:
                cur.execute(f'DROP INDEX IF EXISTS "{name}"')

            with cur.copy(f"COPY patents ({PATENT_COLUMNS}) FROM STDIN") as copy:
                for row in corpus:
                    copy.write_row(
                        (
                            row["patent_id"], row["source"], row["title"], row["abstract"] or "",
                            row["filing_date"], row["publication_date"], row["grant_date"],
                            row["assignee"], row["cpc_codes"], row["cpc_subclasses"],
                            row["main_subclass"] or None, row["n_claims"], row["n_independent"],
                            row["url"],
                        )
                    )  # fmt: skip

            # One COPY stream at a time: a connection cannot run two concurrently.
            chunk_file = pq.ParquetFile(args.dir / "chunks.parquet")
            n_chunks = n_embedded = 0
            with cur.copy(f"COPY patent_chunks ({CHUNK_COLUMNS}) FROM STDIN") as chunk_copy:
                for batch in chunk_file.iter_batches(batch_size=20_000):
                    for row in batch.to_pylist():
                        pub_date, source = patent_info[row["patent_id"]]
                        position = row_index.get(row["chunk_id"])
                        embedding = None
                        if position is not None:
                            embedding = vector_text(matrix[position])
                            n_embedded += 1
                        chunk_copy.write_row(
                            (
                                row["chunk_id"], row["patent_id"], row["chunk_type"], pub_date,
                                source, row["claim_number"], row["seq"], row["text"],
                                row["char_start"], row["char_end"], embedding,
                            )
                        )  # fmt: skip
                        n_chunks += 1

            n_claims = 0
            claim_columns = ["patent_id", "claim_number", "text", "is_independent", "parent_claim"]
            with cur.copy(f"COPY patent_claims ({CLAIM_COLUMNS}) FROM STDIN") as claim_copy:
                for batch in chunk_file.iter_batches(
                    batch_size=20_000, columns=["chunk_type", *claim_columns]
                ):
                    for row in batch.to_pylist():
                        if row["chunk_type"] != "claim":
                            continue
                        claim_copy.write_row(
                            (
                                row["patent_id"], row["claim_number"], row["text"],
                                row["is_independent"], row["parent_claim"],
                            )
                        )  # fmt: skip
                        n_claims += 1
            print(f"copied {n_chunks:,} chunks ({n_embedded:,} embedded), {n_claims:,} claims")

            cur.execute("SET maintenance_work_mem = '1GB'")
            for name, statement in ddl.items():
                step = time.perf_counter()
                try:
                    with conn.transaction():
                        cur.execute(statement)
                except psycopg.errors.DiskFull:
                    # Parallel builds need shared memory (Docker defaults to 64 MB).
                    print(f"{name}: shared memory too small, retrying without parallel workers")
                    cur.execute("SET max_parallel_maintenance_workers = 0")
                    cur.execute(statement)
                print(f"built {name} in {time.perf_counter() - step:.1f}s")
            for table in ("patents", "patent_claims", "patent_chunks"):
                cur.execute(f"ANALYZE {table}")
        conn.commit()
    print(f"loaded in {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
