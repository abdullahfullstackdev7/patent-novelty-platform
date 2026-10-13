"""Corpus build -> embedding shards -> COPY load, with fake vectors and the test database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import build_corpus
import embed_corpus
import load_to_postgres
import pyarrow.parquet as pq
from sqlalchemy import text
from support import FakeEmbedder

SENTENCE = "The controller receives sensor readings and updates the stored model parameters. "
LONG = SENTENCE * 12


def demo_record(number: int) -> dict:
    return {
        "patent_id": f"US{number}A1",
        "source": "HUPD_APP",
        "title": f"Sensor model {number}",
        "abstract": "A controller updates model parameters from sensor readings. " * 3,
        "claims": [
            {"number": 1, "text": "A controller comprising a sensor input.", "is_independent": True,
             "parent": None},
            {"number": 2, "text": "The controller of claim 1, wherein X.", "is_independent": False,
             "parent": 1},
        ],
        "summary": LONG,
        "description": LONG * 2,
        "filing_date": "2016-01-04",
        "publication_date": f"2016-0{number}-15",
        "grant_date": None,
        "assignee": None,
        "cpc_codes": ["G06N3000", "H04L9000"],
        "url": f"https://patents.google.com/patent/US{number}A1",
    }  # fmt: skip


def build_processed(tmp_path: Path) -> Path:
    source = tmp_path / "patents.jsonl"
    source.write_text("\n".join(json.dumps(demo_record(n)) for n in (1, 2, 3)), encoding="utf-8")
    out = tmp_path / "processed"
    build_corpus.build(
        argparse.Namespace(
            hupd=None, patentsview_years=None, patentsview_dir="", demo_jsonl=str(source),
            cpc=build_corpus.TARGET_CPC, max_hupd=10, max_patentsview=10, max_summary_chunks=20,
            max_description_chunks=40, demo_size=3, write_demo=False, out=out,
        )
    )  # fmt: skip
    return out


def embed_into_shards(directory: Path, types: set[str], shard_size: int = 5) -> int:
    """Same flow as embed_corpus.main with the fake embedder, small shards."""
    table = pq.read_table(directory / "chunks.parquet", columns=["chunk_id", "chunk_type", "text"])
    rows = [r for r in table.to_pylist() if r["chunk_type"] in types]
    shard_dir = directory / "embeddings"
    shard_dir.mkdir(exist_ok=True)
    embedder = FakeEmbedder()
    for index, start in enumerate(range(0, len(rows), shard_size)):
        part = rows[start : start + shard_size]
        vectors = embedder.encode_documents([r["text"] for r in part])
        embed_corpus.write_shard(shard_dir, index, [r["chunk_id"] for r in part], vectors)
    return len(rows)


def test_existing_ids_makes_embedding_resumable(tmp_path):
    processed = build_processed(tmp_path)
    expected = embed_into_shards(processed, {"claim", "abstract"})
    done, shard_count = embed_corpus.existing_ids(processed / "embeddings")
    assert len(done) == expected == 3 * 3  # 2 claims + 1 abstract per patent
    assert shard_count == 2
    assert "US1A1:claim:1" in done and "US1A1:summary:0" not in done


def test_load_copies_rows_embeddings_and_rebuilds_heavy_indexes(
    tmp_path, monkeypatch, database_url
):
    processed = build_processed(tmp_path)
    embedded = embed_into_shards(processed, {"claim", "abstract", "summary"})

    monkeypatch.setattr(
        sys, "argv", ["load", "--dir", str(processed), "--database-url", database_url]
    )
    load_to_postgres.main()

    from sqlalchemy import create_engine

    engine = create_engine(database_url)
    with engine.connect() as conn:
        count = lambda sql: conn.execute(text(sql)).scalar_one()  # noqa: E731
        assert count("SELECT count(*) FROM patents") == 3
        assert count("SELECT count(*) FROM patent_claims") == 6
        assert count("SELECT count(*) FROM patent_chunks") == len(
            pq.read_table(processed / "chunks.parquet")
        )
        assert count("SELECT count(*) FROM patent_chunks WHERE embedding IS NOT NULL") == embedded
        assert (
            count(
                "SELECT count(*) FROM patent_chunks WHERE type = 'description' "
                "AND embedding IS NOT NULL"
            )
            == 0
        )
        assert count("SELECT count(*) FROM patent_chunks WHERE tsv IS NULL") == 0
        # denormalized search columns copied from the patent
        assert (
            count(
                "SELECT count(*) FROM patent_chunks c JOIN patents p ON p.id = c.patent_id "
                "WHERE c.publication_date <> p.publication_date OR c.source <> p.source"
            )
            == 0
        )
        indexes = {r[0] for r in conn.execute(text("SELECT indexname FROM pg_indexes"))}
        assert {"ix_patent_chunks_embedding_hnsw", "ix_patent_chunks_tsv"} <= indexes
        row = conn.execute(
            text(
                "SELECT cpc_subclasses, is_independent FROM patents p JOIN patent_claims c "
                "ON c.patent_id = p.id WHERE p.id = 'US1A1' AND c.number = 2"
            )
        ).one()
        assert row[0] == ["G06N", "H04L"] and row[1] is False

    # running it again replaces the data instead of duplicating it
    load_to_postgres.main()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM patents")).scalar_one() == 3
    engine.dispose()


def test_vector_text_round_trip_format():
    import numpy as np

    assert (
        load_to_postgres.vector_text(np.array([0.5, -1.0, 0.0], dtype=np.float32)) == "[0.5,-1,0]"
    )
    assert set(load_to_postgres.heavy_index_ddl()) == {
        "ix_patent_chunks_tsv",
        "ix_patent_chunks_embedding_hnsw",
    }
    assert "USING hnsw" in load_to_postgres.heavy_index_ddl()["ix_patent_chunks_embedding_hnsw"]
