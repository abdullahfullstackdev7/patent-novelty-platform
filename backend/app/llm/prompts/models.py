"""Output models for the prompt tasks. Pydantic is the single source of truth: the same model
validates the answer and, after provider_schema(), constrains the provider's output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RATIONALE_WORDS = 25
SUMMARY_WORDS = 350


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ElementItem(Strict):
    id: str = Field(pattern=r"^E\d{1,2}$")
    text: str = Field(min_length=1, max_length=400)

    @field_validator("text")
    @classmethod
    def _single_line(cls, value: str) -> str:
        return " ".join(value.split())


class ParseElementsOut(Strict):
    elements: list[ElementItem] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _unique_ids(self) -> ParseElementsOut:
        ids = [e.id for e in self.elements]
        if len(set(ids)) != len(ids):
            raise ValueError("element ids must be unique")
        return self


class ChartCellItem(Strict):
    e: str = Field(pattern=r"^E\d{1,2}$")
    s: Literal["d", "p", "n"]
    p: str = Field(max_length=200)
    r: str = Field(max_length=400)

    @field_validator("r", mode="before")
    @classmethod
    def _cap_rationale(cls, value: object) -> object:
        """The rationale cap is enforced by truncation: it is free, a repair call is not.
        Runs before the length constraint so a long rationale is trimmed, not rejected."""
        if not isinstance(value, str):
            return value
        return " ".join(value.split()[:RATIONALE_WORDS])


class ChartOut(Strict):
    cells: list[ChartCellItem] = Field(min_length=1, max_length=30)


class SummaryOut(Strict):
    summary: str = Field(min_length=1, max_length=4000)

    @field_validator("summary")
    @classmethod
    def _word_limit(cls, value: str) -> str:
        if len(value.split()) > SUMMARY_WORDS:
            raise ValueError(f"summary must be at most {SUMMARY_WORDS} words")
        return value.strip()
