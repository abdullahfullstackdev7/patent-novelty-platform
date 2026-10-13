from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command

BACKEND = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    # reference
    "patents", "patent_claims", "patent_chunks",
    # case
    "cases", "case_shares", "disclosures", "disclosure_elements", "search_runs",
    "search_results", "claim_charts", "chart_cells", "reports", "report_versions",
    "review_events",
    # platform
    "users", "roles", "audit_log", "jobs", "llm_calls", "llm_cache",
    # business
    "clients", "plans", "subscriptions", "invoices", "invoice_lines", "usage_events",
}  # fmt: skip


def index_definitions(engine: Engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT indexname, indexdef FROM pg_indexes"))
        return {name: definition for name, definition in rows}


def test_every_planned_table_exists(engine: Engine):
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_hnsw_index_uses_cosine_ops_and_planned_parameters(engine: Engine):
    definition = index_definitions(engine)["ix_patent_chunks_embedding_hnsw"]
    assert "USING hnsw" in definition
    assert "vector_cosine_ops" in definition
    assert "m='16'" in definition or "m=16" in definition
    assert "ef_construction='128'" in definition or "ef_construction=128" in definition


def test_gin_and_btree_indexes_exist(engine: Engine):
    indexes = index_definitions(engine)
    assert "USING gin" in indexes["ix_patent_chunks_tsv"]
    assert "USING gin" in indexes["ix_patents_cpc_codes_gin"]
    for name in ("ix_patents_publication_date", "ix_patents_grant_date", "ix_cases_created_at"):
        assert "USING btree" in indexes[name]


def test_roles_are_seeded(engine: Engine):
    with engine.connect() as conn:
        names = {row[0] for row in conn.execute(text("SELECT name FROM roles"))}
    assert names == {"admin", "attorney", "analyst", "viewer"}


def test_tsv_is_a_generated_column(seeded):
    with seeded() as session:
        row = session.execute(
            text("SELECT tsv::text FROM patent_chunks WHERE id = 'US100A1:abstract:0'")
        ).one()
    assert "thermal" in row[0] and "imped" in row[0]


def test_source_constraint_rejects_unknown_source(engine: Engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO patents (id, source, title, publication_date) "
                "VALUES ('X', 'OTHER', 't', '2016-01-01')"
            )
        )


def test_search_results_do_not_block_corpus_reload(engine: Engine):
    """patent_id on case history has no foreign key, so truncating patents is always allowed."""
    foreign = inspect(engine).get_foreign_keys("search_results")
    assert all(fk["referred_table"] != "patents" for fk in foreign)
    foreign = inspect(engine).get_foreign_keys("chart_cells")
    assert all(fk["referred_table"] != "patents" for fk in foreign)


def test_migration_downgrade_and_upgrade_round_trip(database_url: str):
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
