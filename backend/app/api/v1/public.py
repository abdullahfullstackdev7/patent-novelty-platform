"""Public website endpoints: plans, corpus figures and the contact form. No login required."""

# No `from __future__ import annotations` here: slowapi wraps the endpoints (see auth.py).
import re
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select

from app.api.deps import SessionDep, ip_of
from app.api.v1.schemas import StrictModel
from app.db.models import ContactMessage, Patent, PatentChunk, Plan
from app.security.http import contact_limit, limiter

router = APIRouter(prefix="/public", tags=["public"])

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
CACHE = "public, max-age=300"


class PlanOut(BaseModel):
    code: str
    name: str
    monthly_price: Decimal
    included_reports: int
    overage_price: Decimal
    seats: int
    extra_seat_price: Decimal


class CorpusStats(BaseModel):
    patents: int
    chunks: int
    sources: list[str]


class ContactRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    organization: str | None = Field(default=None, max_length=200)
    topic: Literal["demo", "sales", "support", "other"] = "demo"
    message: str = Field(min_length=10, max_length=4000)
    # Honeypot: hidden in the form, so only bots fill it. Such requests are dropped silently.
    website: str | None = Field(default=None, max_length=200)

    @field_validator("name", "organization", "message", "website", mode="before")
    @classmethod
    def _clean(cls, value):
        if isinstance(value, str):
            if _CONTROL.search(value.replace("\n", "").replace("\r", "").replace("\t", "")):
                raise ValueError("control characters are not allowed")
            return value.strip() or None
        return value

    @field_validator("name", "message")
    @classmethod
    def _required(cls, value):
        if not value:
            raise ValueError("must not be blank")
        return value


@router.get("/plans", response_model=list[PlanOut])
def plans(session: SessionDep, response: Response):
    """The plans table as seeded, cheapest first. The pricing pages render this."""
    response.headers["Cache-Control"] = CACHE
    rows = session.scalars(select(Plan).order_by(Plan.monthly_price)).all()
    return [PlanOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/stats", response_model=CorpusStats)
def stats(session: SessionDep, response: Response):
    """Real size of the loaded corpus, so the website never states a number it cannot back."""
    response.headers["Cache-Control"] = CACHE
    patents = session.scalar(select(func.count()).select_from(Patent)) or 0
    chunks = session.scalar(select(func.count()).select_from(PatentChunk)) or 0
    sources = list(session.scalars(select(Patent.source).distinct().order_by(Patent.source)))
    return CorpusStats(patents=patents, chunks=chunks, sources=sources)


@router.post("/contact", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(contact_limit)
def contact(request: Request, body: ContactRequest, session: SessionDep):
    if body.website:  # a bot; answer like a success so it learns nothing
        return {"received": True}
    session.add(
        ContactMessage(
            name=body.name,
            email=str(body.email).lower(),
            organization=body.organization,
            topic=body.topic,
            message=body.message,
            ip_address=ip_of(request),
        )
    )
    session.commit()
    return {"received": True}
