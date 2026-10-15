"""Database backup, restore and a restore check.

    python scripts/backup_db.py backup  backups/priorart.dump
    python scripts/backup_db.py restore backups/priorart.dump --into priorart_restore
    python scripts/backup_db.py verify  backups/priorart.dump        # restore to a scratch database, compare, drop it

Connection settings come from DATABASE_URL (default: the development database). When the
database runs in Docker, pass --docker-container NAME and the tools run inside that container, so
no PostgreSQL client is needed on the host. Dumps use the custom format, which pg_restore can
restore selectively and in parallel. The dump holds encrypted case content as stored; keep the
FERNET_KEY backup separate from the dump.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_URL = "postgresql://priorart:priorart@localhost:54329/priorart"


@dataclass(frozen=True)
class Target:
    user: str
    password: str
    host: str
    port: int
    database: str
    container: str | None = None


def parse_url(url: str, container: str | None = None) -> Target:
    parsed = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
    return Target(
        unquote(parsed.username or "postgres"),
        unquote(parsed.password or ""),
        parsed.hostname or "localhost",
        parsed.port or 5432,
        (parsed.path or "/postgres").lstrip("/"),
        container,
    )


def _command(target: Target, tool: str, args: list[str], interactive: bool = False) -> list[str]:
    """The command line for a PostgreSQL tool, run inside the container when one is named."""
    if target.container:
        prefix = ["docker", "exec", *(["-i"] if interactive else []), "-e", f"PGPASSWORD={target.password}", target.container]
        return [*prefix, tool, "-U", target.user, *args]
    return [tool, "-h", target.host, "-p", str(target.port), "-U", target.user, *args]


def _env(target: Target) -> dict[str, str]:
    return {**os.environ, "PGPASSWORD": target.password}


def run(command: list[str], target: Target, **kwargs: object) -> subprocess.CompletedProcess:
    return subprocess.run(command, env=_env(target), check=True, **kwargs)  # noqa: S603


def backup(target: Target, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        run(_command(target, "pg_dump", ["-Fc", "--no-owner", target.database]), target, stdout=handle)
    return output.stat().st_size


def sql(target: Target, statement: str, database: str | None = None) -> str:
    command = _command(target, "psql", ["-d", database or target.database, "-At", "-c", statement])
    return run(command, target, capture_output=True, text=True).stdout.strip()


def restore(target: Target, dump: Path, into: str) -> None:
    admin = Target(**{**target.__dict__, "database": "postgres"})
    sql(admin, f'DROP DATABASE IF EXISTS "{into}"', "postgres")
    sql(admin, f'CREATE DATABASE "{into}"', "postgres")
    command = _command(target, "pg_restore", ["--no-owner", "-d", into], interactive=True)
    with dump.open("rb") as handle:
        run(command, target, stdin=handle)


def table_counts(target: Target, database: str) -> dict[str, int]:
    """Exact row count of every table in the public schema."""
    names = sql(target, "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1", database).splitlines()
    return {name: int(sql(target, f'SELECT count(*) FROM "{name}"', database)) for name in names}


def differences(original: dict[str, int], restored: dict[str, int]) -> list[str]:
    """Human-readable differences between two sets of table counts. Empty means identical."""
    out = [f"{t}: missing after restore" for t in sorted(original.keys() - restored.keys())]
    out += [f"{t}: unexpected table after restore" for t in sorted(restored.keys() - original.keys())]
    out += [f"{t}: {original[t]} rows before, {restored[t]} after" for t in sorted(original.keys() & restored.keys()) if original[t] != restored[t]]
    return out


def verify(target: Target, dump: Path, scratch: str | None = None) -> list[str]:
    scratch = scratch or f"{target.database}_restore_check"
    try:
        restore(target, dump, scratch)
        return differences(table_counts(target, target.database), table_counts(target, scratch))
    finally:
        admin = Target(**{**target.__dict__, "database": "postgres"})
        sql(admin, f'DROP DATABASE IF EXISTS "{scratch}"', "postgres")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("backup", "restore", "verify"))
    parser.add_argument("dump", type=Path)
    parser.add_argument("--into", help="database name to restore into (restore only)")
    parser.add_argument("--docker-container", help="run pg_dump and friends inside this container")
    args = parser.parse_args()
    target = parse_url(os.environ.get("DATABASE_URL", DEFAULT_URL), args.docker_container)

    if args.action == "backup":
        print(f"wrote {args.dump} ({backup(target, args.dump):,} bytes)")
    elif args.action == "restore":
        if not args.into:
            sys.exit("--into is required for restore")
        restore(target, args.dump, args.into)
        print(f"restored into {args.into}")
    else:
        problems = verify(target, args.dump)
        if problems:
            sys.exit("restore check FAILED:\n  " + "\n  ".join(problems))
        print("restore check passed: every table has the same row count after restore")


if __name__ == "__main__":
    main()
