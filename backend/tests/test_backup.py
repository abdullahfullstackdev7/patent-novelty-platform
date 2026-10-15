"""Backup and restore: the helpers, and a real dump and restore of the test database when Docker is available."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_db.py"
spec = importlib.util.spec_from_file_location("backup_db", SCRIPT)
backup_db = importlib.util.module_from_spec(spec)
sys.modules["backup_db"] = backup_db
spec.loader.exec_module(backup_db)


def test_connection_urls_are_parsed_including_the_sqlalchemy_form():
    t = backup_db.parse_url("postgresql+psycopg://app:p%40ss@db.internal:6543/atlas")
    assert (t.user, t.password, t.host, t.port, t.database) == ("app", "p@ss", "db.internal", 6543, "atlas")
    d = backup_db.parse_url("postgresql://u:p@localhost/x", "priorart-db")
    assert d.port == 5432 and d.container == "priorart-db"


def test_commands_run_inside_the_container_when_one_is_named():
    host = backup_db.parse_url("postgresql://u:p@h:1/d")
    assert backup_db._command(host, "pg_dump", ["-Fc", "d"]) == ["pg_dump", "-h", "h", "-p", "1", "-U", "u", "-Fc", "d"]
    docker = backup_db.parse_url("postgresql://u:secret@h:1/d", "c1")
    command = backup_db._command(docker, "pg_restore", ["-d", "x"], interactive=True)
    assert command == ["docker", "exec", "-i", "-e", "PGPASSWORD=secret", "c1", "pg_restore", "-U", "u", "-d", "x"]
    assert "-h" not in command  # the container reaches its own server directly


def test_differences_name_every_kind_of_mismatch():
    assert backup_db.differences({"a": 1, "b": 2}, {"a": 1, "b": 2}) == []
    found = backup_db.differences({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 5, "d": 0})
    assert found == ["c: missing after restore", "d: unexpected table after restore", "b: 2 rows before, 5 after"]


def docker_container() -> str | None:
    if shutil.which("docker") is None:
        return None
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, check=False)
    return "priorart-db" if "priorart-db" in out.stdout.split() else None


@pytest.mark.skipif(docker_container() is None, reason="needs the priorart-db container")
def test_a_backup_restores_to_identical_row_counts(database_url, engine, tmp_path, clean_db, users):
    target = backup_db.parse_url(database_url.replace("+psycopg", ""), "priorart-db")
    dump = tmp_path / "test.dump"
    size = backup_db.backup(target, dump)
    assert size > 1000
    problems = backup_db.verify(target, dump, scratch="priorart_test_restore_check")
    assert problems == []
    assert backup_db.table_counts(target, target.database)["users"] == len(users)


@pytest.mark.skipif(docker_container() is None, reason="needs the priorart-db container")
def test_the_restore_check_fails_when_the_data_changed_after_the_backup(database_url, engine, tmp_path, clean_db, users):
    target = backup_db.parse_url(database_url.replace("+psycopg", ""), "priorart-db")
    dump = tmp_path / "test.dump"
    backup_db.backup(target, dump)
    backup_db.sql(target, "DELETE FROM users WHERE email = (SELECT email FROM users LIMIT 1)")
    problems = backup_db.verify(target, dump, scratch="priorart_test_restore_check")
    assert any(p.startswith("users: ") for p in problems)
