"""Case data: cases, disclosures, search runs, claim charts, reports and review events.

Disclosure text columns hold plain text now. Phase 3 stores Fernet tokens in the same columns.
`patent_id` columns on results and chart cells deliberately have no foreign key so a corpus
reload never rewrites case history.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.platform import UUID_PK


def _ts(**kwargs: Any):
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), **kwargs
    )


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="draft")
    stage: Mapped[str | None] = mapped_column(String(24))
    risk_level: Mapped[str | None] = mapped_column(String(16))
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    priority_date: Mapped[date | None] = mapped_column(Date)
    jurisdiction: Mapped[str] = mapped_column(String(8), nullable=False, server_default="US")
    llm_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="auto")
    confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    retention_days: Mapped[int | None] = mapped_column(Integer)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'running', 'in_review', 'changes_requested', 'approved')",
            name="status_valid",
        ),
        CheckConstraint(
            "risk_level IS NULL OR risk_level IN ('low', 'medium', 'medium_high', 'high')",
            name="risk_level_valid",
        ),
        CheckConstraint(
            "llm_mode IN ('auto', 'groq', 'gemini', 'local_only')", name="llm_mode_valid"
        ),
        Index("ix_cases_owner_id", "owner_id"),
        Index("ix_cases_client_id", "client_id"),
        Index("ix_cases_status", "status"),
        Index("ix_cases_created_at", "created_at"),
    )


class CaseShare(Base):
    __tablename__ = "case_shares"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    permission: Mapped[str] = mapped_column(String(8), nullable=False, server_default="read")
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        PrimaryKeyConstraint("case_id", "user_id"),
        CheckConstraint("permission IN ('read', 'write')", name="permission_valid"),
    )


class Disclosure(Base):
    __tablename__ = "disclosures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    technical_field: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    problem: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    solution: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    content_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class DisclosureElement(Base):
    __tablename__ = "disclosure_elements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    disclosure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("disclosures.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(8), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="user")
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("disclosure_id", "key", name="uq_disclosure_elements_disclosure_id_key"),
        CheckConstraint("source IN ('user', 'llm', 'local')", name="source_valid"),
    )


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    suggested_cpc: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    timings_ms: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="done")
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_search_runs_case_id", "case_id"),)


class SearchResult(Base):
    __tablename__ = "search_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search_runs.id", ondelete="CASCADE"), nullable=False
    )
    patent_id: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    fused_score: Mapped[float | None] = mapped_column(Float)
    rerank_score: Mapped[float | None] = mapped_column(Float)
    matched_chunk_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    in_chart: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("run_id", "patent_id", name="uq_search_results_run_id_patent_id"),
        Index("ix_search_results_run_id_rank", "run_id", "rank"),
    )


class ClaimChart(Base):
    __tablename__ = "claim_charts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class ChartCell(Base):
    __tablename__ = "chart_cells"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    chart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claim_charts.id", ondelete="CASCADE"), nullable=False
    )
    element_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("disclosure_elements.id", ondelete="CASCADE"), nullable=False
    )
    patent_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    passage_id: Mapped[str | None] = mapped_column(Text)
    excerpt: Mapped[str | None] = mapped_column(Text)
    # Offsets of the excerpt inside the text of chunk `passage_id`, for highlighting.
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    # Hash of everything the cell was computed from. A rerun skips cells whose hash is unchanged.
    input_hash: Mapped[str | None] = mapped_column(String(64))
    rationale: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    original: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    override_reason: Mapped[str | None] = mapped_column(Text)
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint(
            "chart_id",
            "element_id",
            "patent_id",
            name="uq_chart_cells_chart_id_element_id_patent_id",
        ),
        CheckConstraint("status IN ('disclosed', 'partial', 'not_found')", name="status_valid"),
        CheckConstraint("method IN ('local', 'llm')", name="method_valid"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_chart_cells_chart_id", "chart_id"),
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False, server_default="draft")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint(
            "state IN ('draft', 'in_review', 'changes_requested', 'approved')",
            name="state_valid",
        ),
    )


class ReportVersion(Base):
    __tablename__ = "report_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **UUID_PK)
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("report_id", "version", name="uq_report_versions_report_id_version"),
    )


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cell_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chart_cells.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_review_events_case_id_created_at", "case_id", "created_at"),)
