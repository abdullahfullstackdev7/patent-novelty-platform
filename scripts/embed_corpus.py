"""Embed corpus chunks with bge-small-en-v1.5 (CPU, normalized).

    uv run --project backend python scripts/embed_corpus.py --dir dataset/processed
    uv run --project backend python scripts/embed_corpus.py --dir dataset/processed --types \
        claim abstract summary description

Output: <dir>/embeddings/part-00000.parquet, part-00001.parquet, ... with columns
`chunk_id` and `embedding` (384 float32). Shards make the job resumable: a rerun skips every
chunk id that is already in a shard. The command runs short-lived worker processes and
restarts a worker that crashes, as long as it made progress (CPU torch can crash under memory
pressure on small machines). Search only needs claim and abstract chunks, summary chunks
feed passage selection in Phase 5, so description chunks are opt-in (`--types`).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from _common import PROCESSED

DEFAULT_TYPES = ["claim", "abstract", "summary"]
BLOCK = 256  # texts per model call, sentence-transformers sorts by length inside a call
BATCH_SIZE = 16  # small batches keep peak memory low on constrained machines
MAX_TOKENS = 256  # passages are at most 150 words, only very long claims are truncated


def existing_ids(shard_dir: Path) -> tuple[set[str], int]:
    done: set[str] = set()
    shards = sorted(shard_dir.glob("part-*.parquet"))
    for shard in shards:
        done.update(pq.read_table(shard, columns=["chunk_id"]).column("chunk_id").to_pylist())
    return done, len(shards)


def write_shard(shard_dir: Path, index: int, ids: list[str], vectors: np.ndarray) -> None:
    table = pa.table(
        {
            "chunk_id": pa.array(ids, pa.string()),
            "embedding": pa.FixedSizeListArray.from_arrays(
                pa.array(vectors.reshape(-1), pa.float32()), vectors.shape[1]
            ),
        }
    )
    target = shard_dir / f"part-{index:05d}.parquet"
    temporary = target.with_suffix(".tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(target)  # atomic, so a killed run never leaves a half shard


def supervise(args: argparse.Namespace) -> int:
    """Run workers until every wanted chunk is embedded, restarting crashed ones."""
    shard_dir = args.dir / "embeddings"
    total_limit = args.limit
    started = time.perf_counter()
    base = len(existing_ids(shard_dir)[0]) if shard_dir.exists() else 0
    while True:
        before = len(existing_ids(shard_dir)[0]) if shard_dir.exists() else 0
        if total_limit and before - base >= total_limit:
            break
        slice_size = args.per_process
        if total_limit:
            slice_size = min(slice_size, total_limit - (before - base))
        command = [
            sys.executable, __file__, "--worker", "--dir", str(args.dir),
            "--shard-size", str(args.shard_size), "--limit", str(slice_size),
            "--types", *args.types,
        ]  # fmt: skip
        code = subprocess.run(command, check=False).returncode
        after = len(existing_ids(shard_dir)[0])
        if after == before:
            if code == 0:
                break  # nothing left to embed
            print(f"worker exited with code {code} without progress", file=sys.stderr)
            return 1
        if code != 0:
            print(f"worker crashed with code {code}, progress kept, restarting", flush=True)
    done = len(existing_ids(shard_dir)[0])
    print(
        f"done: {done - base:,} new chunks, {done:,} total in {time.perf_counter() - started:.0f}s"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=PROCESSED)
    parser.add_argument("--types", nargs="+", default=DEFAULT_TYPES)
    parser.add_argument("--shard-size", type=int, default=2_000)
    parser.add_argument("--limit", type=int, help="stop after this many new chunks (smoke runs)")
    parser.add_argument("--per-process", type=int, default=1_000, help="chunks per worker process")
    parser.add_argument("--worker", action="store_true", help="internal: embed one slice")
    args = parser.parse_args()
    if not args.worker:
        raise SystemExit(supervise(args))

    from app.search.embedding import SentenceTransformerEmbedder

    shard_dir = args.dir / "embeddings"
    shard_dir.mkdir(parents=True, exist_ok=True)
    done, shard_index = existing_ids(shard_dir)
    print(f"resuming: {len(done):,} chunks already embedded in {shard_index} shard(s)")

    import torch

    torch.set_num_threads(min(8, torch.get_num_threads()))
    embedder = SentenceTransformerEmbedder(batch_size=BATCH_SIZE, max_seq_length=MAX_TOKENS)
    wanted = set(args.types)
    pending_ids: list[str] = []
    pending_texts: list[str] = []
    out_ids: list[str] = []
    out_vectors: list[np.ndarray] = []
    total = 0
    started = time.perf_counter()

    def embed_pending() -> None:
        nonlocal total
        if not pending_ids:
            return
        out_vectors.append(embedder.encode_documents(pending_texts))
        out_ids.extend(pending_ids)
        total += len(pending_ids)
        pending_ids.clear()
        pending_texts.clear()
        rate = total / (time.perf_counter() - started)
        print(f"  embedded {total:,} new chunks ({rate:.0f}/s)", flush=True)

    def flush_shard() -> None:
        nonlocal shard_index
        if not out_ids:
            return
        write_shard(shard_dir, shard_index, out_ids, np.vstack(out_vectors))
        shard_index += 1
        out_ids.clear()
        out_vectors.clear()

    parquet = pq.ParquetFile(args.dir / "chunks.parquet")
    for batch in parquet.iter_batches(
        batch_size=20_000, columns=["chunk_id", "chunk_type", "text"]
    ):
        for chunk_id, chunk_type, text in zip(
            batch.column("chunk_id").to_pylist(),
            batch.column("chunk_type").to_pylist(),
            batch.column("text").to_pylist(),
            strict=True,
        ):
            if chunk_type not in wanted or chunk_id in done:
                continue
            pending_ids.append(chunk_id)
            pending_texts.append(text)
            if len(pending_ids) >= BLOCK:
                embed_pending()
                if len(out_ids) >= args.shard_size:
                    flush_shard()
            if args.limit and total + len(pending_ids) >= args.limit:
                break
        if args.limit and total + len(pending_ids) >= args.limit:
            break
    embed_pending()
    flush_shard()
    print(f"done: {total:,} new chunks in {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
