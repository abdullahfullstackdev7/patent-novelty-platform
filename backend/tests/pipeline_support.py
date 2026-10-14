"""Helpers for pipeline tests: a task-aware fake LLM, case factory and runner factory."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from llm_support import make_gateway
from support import FakeEmbedder, FakeReranker

from app.config import Settings
from app.db.models import Case
from app.llm.budget import estimate_tokens
from app.llm.types import LLMResult, Message
from app.pipeline.runner import PipelineRunner
from app.services.disclosures import save_disclosure

# Elements written against the CORPUS fixture (see conftest). E1 copies a claim, so it is a
# local "disclosed". E2 overlaps a dependent claim only partly, so it is ambiguous. E3 matches
# nothing and is a local "not found".
E1 = (
    "A battery management unit comprising an impedance measurement circuit for lithium ion "
    "cells and a gas sensor configured to detect electrolyte vapour in a pack housing."
)
E2 = "a contactor that opens to isolate the battery pack when a fault is detected"
E3 = "quantum teleportation of cheese sandwiches across the ocean"
ELEMENTS = [E1, E2, E3]
PRIORITY = date(2018, 1, 1)


def chart_items(user: str) -> list[dict]:
    """The items of a chart_cells request, read back out of the quoted data block."""
    return json.loads(user.split("\n")[1])["items"]


@dataclass
class PipelineLLM:
    """Answers each task like a model would. Token counts follow the real prompt sizes."""

    name: str = "groq"
    model: str = "fake-model"
    status_for: Any = lambda element: "p"  # noqa: E731
    cite: Any = None  # callable(item) -> passage id, default: the first passage offered
    fail_with: BaseException | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)  # (task, user message)

    def complete(self, task: str, messages: list[Message], schema, max_tokens: int) -> LLMResult:
        user = messages[-1].content
        self.calls.append((task, user))
        if self.fail_with is not None:
            raise self.fail_with
        if task == "chart_cells":
            data: Any = {"cells": [
                {"e": it["e"], "s": self.status_for(it["e"]),
                 "p": self.cite(it) if self.cite else it["ps"][0]["id"],
                 "r": f"The passage relates to {it['e']}."}
                for it in chart_items(user)
            ]}  # fmt: skip
        elif task == "exec_summary":
            data = {"summary": "The charted references were compared element by element. " * 4}
        elif task == "parse_elements":
            data = {
                "elements": [{"id": f"E{i}", "text": f"extracted element {i}"} for i in (1, 2, 3)]
            }
        else:
            raise AssertionError(f"unexpected task {task}")
        text = json.dumps(data)
        return LLMResult(
            text=text, json=data,
            tokens_in=sum(estimate_tokens(m.content) for m in messages),
            tokens_out=estimate_tokens(text), provider=self.name, model=self.model, latency_ms=3,
        )  # fmt: skip

    def tasks(self) -> list[str]:
        return [task for task, _ in self.calls]


def make_case(
    session_factory,
    settings: Settings,
    owner_id: uuid.UUID,
    elements: list[str] | None = None,
    *,
    priority_date: date | None = PRIORITY,
    llm_mode: str = "auto",
    title: str = "Pipeline case",
) -> uuid.UUID:
    with session_factory() as session:
        case = Case(owner_id=owner_id, title=title, priority_date=priority_date, llm_mode=llm_mode,
                    status="running", stage="queued")  # fmt: skip
        session.add(case)
        session.flush()
        save_disclosure(
            session, settings, case.id,
            title="Thermal runaway detector", technical_field="Battery safety",
            problem="Thermal runaway is detected too late to isolate the pack.",
            solution="Measure impedance and gas, then open a contactor.",
            elements=[(text, "user") for text in (elements or ELEMENTS)],
        )  # fmt: skip
        session.commit()
        return case.id


def make_runner(
    session_factory,
    settings: Settings,
    provider: PipelineLLM | None,
    **overrides,
) -> tuple[PipelineRunner, Any]:
    providers = {"groq": provider} if provider is not None else {}
    gateway, _, _ = make_gateway(session_factory, settings, providers, **overrides)
    tuned = gateway.settings
    runner = PipelineRunner(session_factory, tuned, gateway, FakeEmbedder(), FakeReranker())
    return runner, gateway
