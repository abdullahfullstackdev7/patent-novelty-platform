"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-13 11:13:54.674115
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "clients",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("industry", sa.String(length=64), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("segment", sa.String(length=64), nullable=True),
        sa.Column(
            "signed_up_on", sa.Date(), server_default=sa.text("CURRENT_DATE"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
    )
    op.create_table(
        "llm_cache",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_llm_cache")),
    )
    op.create_table(
        "patents",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), server_default="", nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("grant_date", sa.Date(), nullable=True),
        sa.Column("assignee", sa.Text(), nullable=True),
        sa.Column("cpc_codes", sa.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("cpc_subclasses", sa.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("main_subclass", sa.String(length=8), nullable=True),
        sa.Column("n_claims", sa.Integer(), server_default="0", nullable=False),
        sa.Column("n_independent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "source IN ('PV_GRANT', 'HUPD_APP')", name=op.f("ck_patents_source_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patents")),
    )
    op.create_index(
        "ix_patents_cpc_codes_gin", "patents", ["cpc_codes"], unique=False, postgresql_using="gin"
    )
    op.create_index(
        "ix_patents_cpc_subclasses_gin",
        "patents",
        ["cpc_subclasses"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("ix_patents_grant_date", "patents", ["grant_date"], unique=False)
    op.create_index("ix_patents_main_subclass", "patents", ["main_subclass"], unique=False)
    op.create_index("ix_patents_publication_date", "patents", ["publication_date"], unique=False)
    op.create_index("ix_patents_source", "patents", ["source"], unique=False)
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("monthly_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("included_reports", sa.Integer(), nullable=False),
        sa.Column("overage_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("code", name=op.f("uq_plans_code")),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("name", name=op.f("uq_roles_name")),
    )
    op.create_table(
        "patent_chunks",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("patent_id", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("claim_number", sa.Integer(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "type IN ('claim', 'abstract', 'summary', 'description')",
            name=op.f("ck_patent_chunks_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["patent_id"],
            ["patents.id"],
            name=op.f("fk_patent_chunks_patent_id_patents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patent_chunks")),
    )
    op.create_index(
        "ix_patent_chunks_embedding_hnsw",
        "patent_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 128},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_patent_chunks_patent_id", "patent_chunks", ["patent_id"], unique=False)
    op.create_index(
        "ix_patent_chunks_tsv", "patent_chunks", ["tsv"], unique=False, postgresql_using="gin"
    )
    op.create_index("ix_patent_chunks_type", "patent_chunks", ["type"], unique=False)
    op.create_table(
        "patent_claims",
        sa.Column("patent_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_independent", sa.Boolean(), nullable=False),
        sa.Column("parent", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["patent_id"],
            ["patents.id"],
            name=op.f("fk_patent_claims_patent_id_patents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("patent_id", "number", name=op.f("pk_patent_claims")),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled', 'paused')",
            name=op.f("ck_subscriptions_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name=op.f("fk_subscriptions_client_id_clients")
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_subscriptions_plan_id_plans")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index("ix_subscriptions_client_id", "subscriptions", ["client_id"], unique=False)
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("totp_secret", sa.Text(), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name=op.f("fk_users_client_id_clients")
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name=op.f("fk_users_role_id_roles")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_log_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"], unique=False)
    op.create_index(
        "ix_audit_log_user_id_created_at", "audit_log", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "cases",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("stage", sa.String(length=24), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=True),
        sa.Column("risk_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("priority_date", sa.Date(), nullable=True),
        sa.Column("jurisdiction", sa.String(length=8), server_default="US", nullable=False),
        sa.Column("llm_mode", sa.String(length=16), server_default="auto", nullable=False),
        sa.Column("confidential", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "llm_mode IN ('auto', 'groq', 'gemini', 'local_only')",
            name=op.f("ck_cases_llm_mode_valid"),
        ),
        sa.CheckConstraint(
            "risk_level IS NULL OR risk_level IN ('low', 'medium', 'medium_high', 'high')",
            name=op.f("ck_cases_risk_level_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'running', 'in_review', 'changes_requested', 'approved')",
            name=op.f("ck_cases_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name=op.f("fk_cases_client_id_clients")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_cases_owner_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cases")),
    )
    op.create_index("ix_cases_client_id", "cases", ["client_id"], unique=False)
    op.create_index("ix_cases_created_at", "cases", ["created_at"], unique=False)
    op.create_index("ix_cases_owner_id", "cases", ["owner_id"], unique=False)
    op.create_index("ix_cases_status", "cases", ["status"], unique=False)
    op.create_table(
        "invoices",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'paid', 'overdue', 'void')",
            name=op.f("ck_invoices_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name=op.f("fk_invoices_client_id_clients")
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_invoices_subscription_id_subscriptions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("number", name=op.f("uq_invoices_number")),
    )
    op.create_index("ix_invoices_client_id", "invoices", ["client_id"], unique=False)
    op.create_index("ix_invoices_period_start", "invoices", ["period_start"], unique=False)
    op.create_index("ix_invoices_status_due_on", "invoices", ["status", "due_on"], unique=False)
    op.create_table(
        "case_shares",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("permission", sa.String(length=8), server_default="read", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "permission IN ('read', 'write')", name=op.f("ck_case_shares_permission_valid")
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_shares_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_case_shares_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("case_id", "user_id", name=op.f("pk_case_shares")),
    )
    op.create_table(
        "claim_charts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_claim_charts_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_charts")),
        sa.UniqueConstraint("case_id", name=op.f("uq_claim_charts_case_id")),
    )
    op.create_table(
        "disclosures",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("technical_field", sa.Text(), server_default="", nullable=False),
        sa.Column("problem", sa.Text(), server_default="", nullable=False),
        sa.Column("solution", sa.Text(), server_default="", nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_disclosures_case_id_cases"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disclosures")),
        sa.UniqueConstraint("case_id", name=op.f("uq_disclosures_case_id")),
    )
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.CheckConstraint(
            "kind IN ('subscription', 'overage', 'addon')", name=op.f("ck_invoice_lines_kind_valid")
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_invoice_lines_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_lines")),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_jobs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_jobs_case_id_cases"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_case_id", "jobs", ["case_id"], unique=False)
    op.create_index("ix_jobs_status_run_after", "jobs", ["status", "run_after"], unique=False)
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cached_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="ok", nullable=False),
        sa.Column("cache_hit", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_llm_calls_case_id_cases"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index("ix_llm_calls_case_id", "llm_calls", ["case_id"], unique=False)
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"], unique=False)
    op.create_index(
        "ix_llm_calls_provider_created_at", "llm_calls", ["provider", "created_at"], unique=False
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'in_review', 'changes_requested', 'approved')",
            name=op.f("ck_reports_state_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_reports_case_id_cases"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint("case_id", name=op.f("uq_reports_case_id")),
    )
    op.create_table(
        "search_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "params", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "suggested_cpc",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "timings_ms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="done", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_search_runs_case_id_cases"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_runs")),
    )
    op.create_index("ix_search_runs_case_id", "search_runs", ["case_id"], unique=False)
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("units", sa.Numeric(precision=12, scale=2), server_default="1", nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_usage_events_case_id_cases"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name=op.f("fk_usage_events_client_id_clients")
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_usage_events_plan_id_plans")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_index(
        "ix_usage_events_client_id_occurred_at",
        "usage_events",
        ["client_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_usage_events_event_type_occurred_at",
        "usage_events",
        ["event_type", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "disclosure_elements",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("disclosure_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=8), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=8), server_default="user", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('user', 'llm')", name=op.f("ck_disclosure_elements_source_valid")
        ),
        sa.ForeignKeyConstraint(
            ["disclosure_id"],
            ["disclosures.id"],
            name=op.f("fk_disclosure_elements_disclosure_id_disclosures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disclosure_elements")),
        sa.UniqueConstraint(
            "disclosure_id", "key", name="uq_disclosure_elements_disclosure_id_key"
        ),
    )
    op.create_table(
        "report_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_report_versions_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_report_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name=op.f("fk_report_versions_report_id_reports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_versions")),
        sa.UniqueConstraint("report_id", "version", name="uq_report_versions_report_id_version"),
    )
    op.create_table(
        "search_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("patent_id", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("fused_score", sa.Float(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("matched_chunk_ids", sa.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("excluded", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("in_chart", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["search_runs.id"],
            name=op.f("fk_search_results_run_id_search_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_results")),
        sa.UniqueConstraint("run_id", "patent_id", name="uq_search_results_run_id_patent_id"),
    )
    op.create_index(
        "ix_search_results_run_id_rank", "search_results", ["run_id", "rank"], unique=False
    )
    op.create_table(
        "chart_cells",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chart_id", sa.UUID(), nullable=False),
        sa.Column("element_id", sa.UUID(), nullable=False),
        sa.Column("patent_id", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("passage_id", sa.Text(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("original", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("overridden_by", sa.UUID(), nullable=True),
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("method IN ('local', 'llm')", name=op.f("ck_chart_cells_method_valid")),
        sa.CheckConstraint(
            "status IN ('disclosed', 'partial', 'not_found')",
            name=op.f("ck_chart_cells_status_valid"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_chart_cells_confidence_range")
        ),
        sa.ForeignKeyConstraint(
            ["chart_id"],
            ["claim_charts.id"],
            name=op.f("fk_chart_cells_chart_id_claim_charts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["element_id"],
            ["disclosure_elements.id"],
            name=op.f("fk_chart_cells_element_id_disclosure_elements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["overridden_by"],
            ["users.id"],
            name=op.f("fk_chart_cells_overridden_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chart_cells")),
        sa.UniqueConstraint(
            "chart_id",
            "element_id",
            "patent_id",
            name="uq_chart_cells_chart_id_element_id_patent_id",
        ),
    )
    op.create_index("ix_chart_cells_chart_id", "chart_cells", ["chart_id"], unique=False)
    op.create_table(
        "review_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("cell_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_review_events_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cell_id"],
            ["chart_cells.id"],
            name=op.f("fk_review_events_cell_id_chart_cells"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_review_events_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_events")),
    )
    op.create_index(
        "ix_review_events_case_id_created_at",
        "review_events",
        ["case_id", "created_at"],
        unique=False,
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index("ix_review_events_case_id_created_at", table_name="review_events")
    op.drop_table("review_events")
    op.drop_index("ix_chart_cells_chart_id", table_name="chart_cells")
    op.drop_table("chart_cells")
    op.drop_index("ix_search_results_run_id_rank", table_name="search_results")
    op.drop_table("search_results")
    op.drop_table("report_versions")
    op.drop_table("disclosure_elements")
    op.drop_index("ix_usage_events_event_type_occurred_at", table_name="usage_events")
    op.drop_index("ix_usage_events_client_id_occurred_at", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index("ix_search_runs_case_id", table_name="search_runs")
    op.drop_table("search_runs")
    op.drop_table("reports")
    op.drop_index("ix_llm_calls_provider_created_at", table_name="llm_calls")
    op.drop_index("ix_llm_calls_created_at", table_name="llm_calls")
    op.drop_index("ix_llm_calls_case_id", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index("ix_jobs_status_run_after", table_name="jobs")
    op.drop_index("ix_jobs_case_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_table("disclosures")
    op.drop_table("claim_charts")
    op.drop_table("case_shares")
    op.drop_index("ix_invoices_status_due_on", table_name="invoices")
    op.drop_index("ix_invoices_period_start", table_name="invoices")
    op.drop_index("ix_invoices_client_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_cases_status", table_name="cases")
    op.drop_index("ix_cases_owner_id", table_name="cases")
    op.drop_index("ix_cases_created_at", table_name="cases")
    op.drop_index("ix_cases_client_id", table_name="cases")
    op.drop_table("cases")
    op.drop_index("ix_audit_log_user_id_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_subscriptions_plan_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_client_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("patent_claims")
    op.drop_index("ix_patent_chunks_type", table_name="patent_chunks")
    op.drop_index("ix_patent_chunks_tsv", table_name="patent_chunks", postgresql_using="gin")
    op.drop_index("ix_patent_chunks_patent_id", table_name="patent_chunks")
    op.drop_index(
        "ix_patent_chunks_embedding_hnsw",
        table_name="patent_chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 128},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("patent_chunks")
    op.drop_table("roles")
    op.drop_table("plans")
    op.drop_index("ix_patents_source", table_name="patents")
    op.drop_index("ix_patents_publication_date", table_name="patents")
    op.drop_index("ix_patents_main_subclass", table_name="patents")
    op.drop_index("ix_patents_grant_date", table_name="patents")
    op.drop_index("ix_patents_cpc_subclasses_gin", table_name="patents", postgresql_using="gin")
    op.drop_index("ix_patents_cpc_codes_gin", table_name="patents", postgresql_using="gin")
    op.drop_table("patents")
    op.drop_table("llm_cache")
    op.drop_table("clients")
    # ### end Alembic commands ###
