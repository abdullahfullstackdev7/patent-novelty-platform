"""Disclosure storage. Disclosure text is Fernet-encrypted at rest."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Disclosure, DisclosureElement
from app.security.crypto import decrypt_text, encrypt_text


@dataclass
class ElementData:
    key: str
    position: int
    text: str
    source: str


@dataclass
class DisclosureData:
    case_id: uuid.UUID
    title: str
    technical_field: str
    problem: str
    solution: str
    elements: list[ElementData]
    content_hash: str | None


def content_hash(
    title: str, technical_field: str, problem: str, solution: str, elements: list[str]
) -> str:
    """Stable hash of the plaintext, used later as an LLM cache key component."""
    canonical = json.dumps(
        [title, technical_field, problem, solution, elements], ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_disclosure(
    session: Session,
    settings: Settings,
    case_id: uuid.UUID,
    *,
    title: str,
    technical_field: str,
    problem: str,
    solution: str,
    elements: list[tuple[str, str]],  # (text, source)
) -> None:
    """Create or replace. Elements are matched by key so unchanged ones keep their ids,
    which keeps their claim chart cells in place."""
    disclosure = session.scalar(select(Disclosure).where(Disclosure.case_id == case_id))
    digest = content_hash(title, technical_field, problem, solution, [t for t, _ in elements])
    if disclosure is None:
        disclosure = Disclosure(case_id=case_id, title=title)
        session.add(disclosure)
    disclosure.title = title
    disclosure.technical_field = encrypt_text(technical_field, settings)
    disclosure.problem = encrypt_text(problem, settings)
    disclosure.solution = encrypt_text(solution, settings)
    disclosure.content_hash = digest
    session.flush()

    existing = {
        e.key: e
        for e in session.scalars(
            select(DisclosureElement).where(DisclosureElement.disclosure_id == disclosure.id)
        )
    }
    for position, (text, source) in enumerate(elements, start=1):
        key = f"E{position}"
        row = existing.pop(key, None)
        if row is None:
            session.add(
                DisclosureElement(
                    disclosure_id=disclosure.id,
                    key=key,
                    position=position,
                    text=encrypt_text(text, settings),
                    source=source,
                )
            )
        elif decrypt_text(row.text, settings) != text or row.source != source:
            row.text = encrypt_text(text, settings)
            row.source = source
    for leftover in existing.values():
        session.delete(leftover)


def load_disclosure(
    session: Session, settings: Settings, case_id: uuid.UUID
) -> DisclosureData | None:
    disclosure = session.scalar(select(Disclosure).where(Disclosure.case_id == case_id))
    if disclosure is None:
        return None
    rows = session.scalars(
        select(DisclosureElement)
        .where(DisclosureElement.disclosure_id == disclosure.id)
        .order_by(DisclosureElement.position)
    ).all()
    return DisclosureData(
        case_id=case_id,
        title=disclosure.title,
        technical_field=decrypt_text(disclosure.technical_field, settings),
        problem=decrypt_text(disclosure.problem, settings),
        solution=decrypt_text(disclosure.solution, settings),
        elements=[
            ElementData(r.key, r.position, decrypt_text(r.text, settings), r.source) for r in rows
        ],
        content_hash=disclosure.content_hash,
    )
