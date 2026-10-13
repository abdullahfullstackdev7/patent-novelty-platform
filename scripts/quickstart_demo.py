"""Quick start: load dataset/demo/ into the dev database and make search work.

    docker compose -f docker/compose.dev-db.yml up -d
    uv run --project backend python scripts/quickstart_demo.py

Steps: apply migrations, build chunks from the committed demo JSONL, embed claims, abstracts
and summaries, bulk load. The target is a working search in under 5 minutes on a laptop CPU
once the embedding model is cached.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from _common import DATASET, ROOT

DEMO_OUT = DATASET / "processed" / "demo"


def run(*command: str, cwd: Path = ROOT) -> None:
    print("\n$", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    started = time.perf_counter()
    python = sys.executable
    run(python, "-m", "alembic", "upgrade", "head", cwd=ROOT / "backend")
    run(
        python, "scripts/build_corpus.py", "--demo-jsonl", "dataset/demo/patents.jsonl",
        "--out", str(DEMO_OUT),
    )  # fmt: skip
    run(python, "scripts/embed_corpus.py", "--dir", str(DEMO_OUT))
    run(python, "scripts/load_to_postgres.py", "--dir", str(DEMO_OUT))
    print(f"\ndemo ready in {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
