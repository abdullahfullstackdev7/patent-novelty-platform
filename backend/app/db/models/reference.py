"""Reference data: the patent corpus (patents, claims, chunks with embeddings)."""

from __future__ import annotations

from datetime import date

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.config import EMBEDDING_DIM
from app.db.base import Base


class Patent(Base):
    __tablename__ = "patents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    filing_date: Mapped[date | None] = mapped_column(Date)
    # Prior-art date: publication date for applications, grant date for grants.
    publication_date: Mapped[date] = mapped_column(Date, nullable=False)
    grant_date: Mapped[date | None] = mapped_column(Date)
    assignee: Mapped[str | None] = mapped_column(Text)
    cpc_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    cpc_subclasses: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    main_subclass: Mapped[str | None] = mapped_column(String(8))
    n_claims: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    n_independent: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    url: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("source IN ('PV_GRANT', 'HUPD_APP')", name="source_valid"),
        Index("ix_patents_publication_date", "publication_date"),
        Index("ix_patents_grant_date", "grant_date"),
        Index("ix_patents_source", "source"),
        Index("ix_patents_main_subclass", "main_subclass"),
        Index("ix_patents_cpc_codes_gin", "cpc_codes", postgresql_using="gin"),
        Index("ix_patents_cpc_subclasses_gin", "cpc_subclasses", postgresql_using="gin"),
    )


class PatentClaim(Base):
    __tablename__ = "patent_claims"

    patent_id: Mapped[str] = mapped_column(
        Text, ForeignKey("patents.id", ondelete="CASCADE"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_independent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    parent: Mapped[int | None] = mapped_column(Integer)


class PatentChunk(Base):
    __tablename__ = "patent_chunks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    patent_id: Mapped[str] = mapped_column(
        Text, ForeignKey("patents.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Copied from patents so date and source filters sit on the same table as the HNSW index.
    publication_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    claim_number: Mapped[int | None] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))

    __table_args__ = (
        CheckConstraint(
            "type IN ('claim', 'abstract', 'summary', 'description')", name="type_valid"
        ),
        Index("ix_patent_chunks_patent_id", "patent_id"),
        Index("ix_patent_chunks_type", "type"),
        # Heavy indexes. The bulk loader drops and recreates them around COPY.
        Index("ix_patent_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_patent_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 128},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


HEAVY_INDEX_NAMES = ("ix_patent_chunks_tsv", "ix_patent_chunks_embedding_hnsw")
