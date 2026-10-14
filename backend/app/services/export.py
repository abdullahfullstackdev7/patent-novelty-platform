"""Report export: HTML rendering with Jinja2 (autoescaped) and PDF through WeasyPrint."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import jinja2
from markupsafe import Markup, escape

from app.pipeline.classify import content_tokens

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
STATUS_LABELS = {
    "disclosed": "Disclosed",
    "partial": "Partial",
    "not_found": "Not found",
    "not_charted": "Not charted",
}
STATUS_SYMBOLS = {"disclosed": "[+]", "partial": "[~]", "not_found": "[-]", "not_charted": "[ ]"}
RISK_LABELS = {"low": "Low", "medium": "Medium", "medium_high": "Medium-High", "high": "High"}
_WORDS = re.compile(r"(\w+)")


class PdfUnavailable(RuntimeError):
    """WeasyPrint or its native libraries (Pango) are not installed on this host."""


def highlight(text: str | None, element: str | None) -> Markup:
    """Escape `text` and wrap the words that match the element's content words in <mark>.

    Matching reuses the pipeline's stemmed content tokens. Everything is escaped first, so a
    hostile excerpt cannot inject markup into the report.
    """
    if not text:
        return Markup("")
    wanted = content_tokens(element or "")
    pieces = []
    for part in _WORDS.split(text):
        if part and _WORDS.fullmatch(part) and content_tokens(part) & wanted:
            pieces.append(Markup("<mark>{}</mark>").format(part))
        else:
            pieces.append(escape(part))
    return Markup("").join(pieces)


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
        autoescape=jinja2.select_autoescape(["html"]),
        undefined=jinja2.StrictUndefined,
    )
    env.filters["highlight"] = highlight
    env.filters["status_label"] = lambda s: STATUS_LABELS.get(s, s)
    env.filters["status_symbol"] = lambda s: STATUS_SYMBOLS.get(s, "")
    env.filters["risk_label"] = lambda s: RISK_LABELS.get(s, s or "Not assessed")
    env.filters["percent"] = lambda v: f"{round(float(v) * 100)}%"
    return env


def normalize_content(content: dict[str, Any]) -> dict[str, Any]:
    """Fill the keys the template reads. Attorney-edited or older versions may lack some."""
    risk = {"level": None, "score": None, "basis": "", "uncovered_elements": []}
    risk.update(content.get("risk") or {})
    filled = {
        "generated_by": "",
        "executive_summary": "",
        "closest_references": [],
        "element_coverage": [],
        "charts": [],
        "claim_drafting_considerations": [],
        "limitations": [],
        "disclaimer": "",
    }
    filled.update(content)
    filled["risk"] = risk
    for ref in filled["closest_references"]:
        ref.setdefault("coverage", {})
    return filled


def render_report_html(payload: dict[str, Any]) -> str:
    """payload is the JSON export: case title, state, version, hash, approval and content."""
    content = normalize_content(dict(payload["content"]))
    element_text = {row["element"]: row["text"] for row in content.get("element_coverage", [])}
    return (
        _environment()
        .get_template("report.html")
        .render(payload=payload, content=content, element_text=element_text)
    )


def html_to_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML
    except OSError as error:  # native libraries missing
        raise PdfUnavailable("PDF rendering is not available on this host") from error
    return HTML(string=html).write_pdf()
