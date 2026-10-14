"""Fixed inputs for prompt golden files and gateway tests."""

from __future__ import annotations

from app.llm import prompts
from app.llm.types import Message

DISCLOSURE = {
    "title": "Thermal runaway detector",
    "technical_field": "Lithium-ion battery safety",
    "problem": "Thermal runaway is detected too late to isolate the pack.",
    "solution": "Measure cell impedance and sense electrolyte gas, then open a contactor.",
}

CHART_ITEMS = [
    {
        "e": "E1",
        "t": "Impedance measurement of lithium-ion cells",
        "ps": [
            {"id": "US100A1:claim:1", "t": "A unit comprising an impedance measurement circuit."},
            {"id": "US100A1:abstract:0", "t": "The unit measures cell impedance and gas."},
        ],
    },
    {
        "e": "E2",
        "t": "Contactor that isolates the pack",
        "ps": [{"id": "US100A1:claim:2", "t": "A contactor isolates the pack."}],
    },
]

SUMMARY_FACTS = {
    "risk": "medium",
    "score": 54,
    "refs": ["US100A1", "US101A1"],
    "elements": [
        {"e": "E1", "disclosed_by": ["US100A1"], "partial_in": []},
        {"e": "E2", "disclosed_by": [], "partial_in": ["US101A1"]},
        {"e": "E3", "disclosed_by": [], "partial_in": []},
    ],
}

CASES = {
    "parse_elements": (prompts.PARSE_ELEMENTS, lambda: prompts.parse_elements_user(**DISCLOSURE)),
    "chart_cells": (prompts.CHART_CELLS, lambda: prompts.chart_cells_user("US100A1", CHART_ITEMS)),
    "exec_summary": (prompts.EXEC_SUMMARY, lambda: prompts.exec_summary_user(SUMMARY_FACTS)),
}


def render(messages: list[Message]) -> str:
    return "\n".join(f"### {m.role}\n{m.content}\n" for m in messages)


def rendered(task: str) -> str:
    spec, build_user = CASES[task]
    return render(spec.messages(build_user()))
