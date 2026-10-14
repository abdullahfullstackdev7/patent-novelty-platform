"""Pipeline over HTTP: extraction, run options, a full API -> queue -> runner -> API round trip."""

from __future__ import annotations

import pytest
from llm_support import make_gateway
from pipeline_support import ELEMENTS, PRIORITY, PipelineLLM
from sqlalchemy import text
from support import FakeEmbedder, FakeReranker

from app.pipeline import queue
from app.pipeline.runner import PipelineRunner
from app.services import export as export_service
from app.worker import make_job_handler

API = "/api/v1"
FIELDS = {
    "title": "Thermal runaway detector",
    "technical_field": "Battery safety",
    "problem": "Thermal runaway is detected too late to isolate the pack.",
    "solution": "A unit measures impedance and a sensor detects gas near the cells; a contactor opens.",
}


@pytest.fixture(autouse=True)
def clean_tables(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE llm_calls, llm_cache, app_settings"))


@pytest.fixture
def llm(app, session_factory, settings):
    """Replace the app's gateway with one backed by a scripted provider."""
    provider = PipelineLLM()
    gateway, _, _ = make_gateway(session_factory, settings, {"groq": provider})
    app.state.llm_gateway = gateway
    provider.gateway = gateway
    return provider


def worker_tick(app, settings) -> bool:
    """Run one queued job exactly like the worker process would."""
    sessions = app.state.session_factory
    runner = PipelineRunner(
        sessions, settings, app.state.llm_gateway, FakeEmbedder(), FakeReranker()
    )
    return queue.process_one(sessions, settings, make_job_handler(runner, settings), "test-worker")


def new_case(client, headers, elements, **extra) -> str:
    created = client.post(
        f"{API}/cases", json={"title": "API pipeline case", **extra}, headers=headers
    )
    case_id = created.json()["id"]
    saved = client.put(
        f"{API}/cases/{case_id}/disclosure",
        json={**FIELDS, "elements": [{"text": t} for t in elements]},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    return case_id


# ---- extraction (the intake checkpoint) ------------------------------------------------------


def test_extraction_with_an_llm_saves_editable_elements_and_is_cached(client, auth, llm, engine):
    case_id = new_case(client, auth["attorney"], [])
    url = f"{API}/cases/{case_id}/disclosure/extract-elements"

    first = client.post(url, headers=auth["attorney"])
    assert first.status_code == 200
    body = first.json()
    assert body["source"] == "llm" and body["tokens"] > 0 and body["cache_hit"] is False
    assert [e["id"] for e in body["elements"]] == ["E1", "E2", "E3"]
    assert {e["source"] for e in body["elements"]} == {"llm"}

    assert client.post(url, headers=auth["attorney"]).status_code == 409  # would overwrite edits
    again = client.post(url + "?replace=true", headers=auth["attorney"]).json()
    assert again["cache_hit"] is True and again["tokens"] == 0  # identical request: free

    # the user can now edit them: a PUT keeps the element ids that are still there
    texts = [e["text"] for e in again["elements"]]
    edited = client.put(
        f"{API}/cases/{case_id}/disclosure",
        json={
            **FIELDS,
            "elements": [{"text": texts[0]}, {"text": "an edited element", "source": "user"}],
        },
        headers=auth["attorney"],
    )
    assert [(e["id"], e["source"]) for e in edited.json()["elements"]] == [
        ("E1", "user"),
        ("E2", "user"),
    ]
    with engine.connect() as conn:
        used = conn.execute(
            text("SELECT detail FROM audit_log WHERE action = 'elements_extracted' ORDER BY id")
        ).all()
    assert used[0][0]["source"] == "llm" and used[0][0]["used"] > 0 and used[1][0]["used"] == 0
    assert llm.tasks() == ["parse_elements"]


def test_extraction_without_an_llm_falls_back_to_local_clauses(client, auth):
    case_id = new_case(client, auth["attorney"], [])
    response = client.post(
        f"{API}/cases/{case_id}/disclosure/extract-elements", headers=auth["attorney"]
    )
    body = response.json()
    assert response.status_code == 200 and body["source"] == "local" and body["tokens"] == 0
    assert body["fallback_reason"] == "AllProvidersUnavailable" and len(body["elements"]) >= 2
    assert {e["source"] for e in body["elements"]} == {"local"}


def test_extraction_respects_a_local_only_case(client, auth, llm):
    case_id = new_case(client, auth["attorney"], [], llm_mode="local_only")
    body = client.post(
        f"{API}/cases/{case_id}/disclosure/extract-elements", headers=auth["attorney"]
    ).json()
    assert body["source"] == "local" and body["fallback_reason"] == "local_only"
    assert llm.calls == []  # the model was never contacted


def test_extraction_preconditions_and_permissions(client, auth, users):
    attorney = auth["attorney"]
    bare = client.post(f"{API}/cases", json={"title": "no disclosure"}, headers=attorney).json()[
        "id"
    ]
    assert (
        client.post(f"{API}/cases/{bare}/disclosure/extract-elements", headers=attorney).status_code
        == 409
    )

    empty = client.post(f"{API}/cases", json={"title": "x"}, headers=attorney).json()["id"]
    client.put(
        f"{API}/cases/{empty}/disclosure", json={"title": "x", "elements": []}, headers=attorney
    )
    unusable = client.post(f"{API}/cases/{empty}/disclosure/extract-elements", headers=attorney)
    assert unusable.status_code == 422  # nothing to derive elements from

    case_id = new_case(client, attorney, [])
    client.post(f"{API}/cases/{case_id}/shares", headers=attorney,
                json={"user_id": str(users["viewer"].id), "permission": "read"})  # fmt: skip
    url = f"{API}/cases/{case_id}/disclosure/extract-elements"
    assert client.post(url, headers=auth["viewer"]).status_code == 403
    assert client.post(url, headers=auth["analyst"]).status_code == 404
    assert (
        client.post(f"{API}/cases/{case_id}/run", headers=attorney).status_code == 409
    )  # no elements
    assert client.post(url, headers=auth["admin"]).status_code == 200


# ---- run options ---------------------------------------------------------------------------------


def test_run_options_are_validated_and_stored_in_the_job(client, auth, engine):
    case_id = new_case(client, auth["attorney"], ELEMENTS)
    url = f"{API}/cases/{case_id}/run"
    for bad in ({"references": 0}, {"references": 6}, {"references": "many"}, {"surprise": 1}):
        assert client.post(url, json=bad, headers=auth["attorney"]).status_code == 422
    assert (
        client.post(
            url, json={"references": 2, "force_search": True}, headers=auth["attorney"]
        ).status_code
        == 202
    )
    with engine.connect() as conn:
        payload = conn.execute(text("SELECT payload FROM jobs")).scalar_one()
    assert payload["options"] == {"references": 2, "force_search": True}


def test_run_without_a_body_uses_the_defaults(client, auth, engine):
    case_id = new_case(client, auth["attorney"], ELEMENTS)
    assert client.post(f"{API}/cases/{case_id}/run", headers=auth["attorney"]).status_code == 202
    with engine.connect() as conn:
        assert conn.execute(text("SELECT payload FROM jobs")).scalar_one()["options"] == {
            "references": 3, "force_search": False}  # fmt: skip


# ---- the whole round trip ---------------------------------------------------------------------------


def test_api_to_worker_to_api_round_trip(
    client, auth, seeded, llm, app, settings, engine, monkeypatch
):
    attorney = auth["attorney"]
    case_id = new_case(client, attorney, ELEMENTS, priority_date=PRIORITY.isoformat())
    base = f"{API}/cases/{case_id}"

    # nothing has run yet
    assert client.get(f"{base}/risk", headers=attorney).json()["level"] is None
    assert client.get(f"{base}/chart", headers=attorney).json()["cells"] == []

    started = client.post(f"{base}/run", json={"references": 3}, headers=attorney)
    assert started.status_code == 202 and started.json()["status"] == "queued"
    assert client.get(f"{base}", headers=attorney).json()["status"] == "running"

    assert worker_tick(app, settings) is True  # the worker picks the job up and runs it
    assert worker_tick(app, settings) is False  # queue drained

    progress = client.get(f"{base}/progress", headers=attorney)  # ends by itself: job finished
    assert '"status": "succeeded"' in progress.text and '"stage": "done"' in progress.text
    assert '"tokens_used"' in progress.text
    case = client.get(base, headers=attorney).json()
    assert case["status"] == "draft" and case["stage"] == "done" and case["risk_level"] is not None

    results = client.get(f"{base}/results", headers=attorney).json()
    assert len(results["results"]) >= 3 and results["results"][0]["patent_id"] == "US100A1"
    assert sum(r["in_chart"] for r in results["results"]) == 3
    assert results["suggested_cpc"] and "US106A1" not in {
        r["patent_id"] for r in results["results"]
    }

    chart = client.get(f"{base}/chart", headers=attorney).json()
    assert len(chart["references"]) == 3 and len(chart["cells"]) == 9
    cell = next(c for c in chart["cells"] if c["patent_id"] == "US100A1" and c["element"] == "E1")
    assert cell["status"] == "disclosed" and cell["method"] == "local" and cell["excerpt"]
    assert cell["char_start"] is not None and cell["char_end"] > cell["char_start"]

    risk = client.get(f"{base}/risk", headers=attorney).json()
    assert risk["level"] == case["risk_level"] and risk["score"] == case["risk_score"]
    assert [r["element"] for r in risk["per_element"]] == ["E1", "E2", "E3"]
    assert (
        len(risk["references"]) == 3
        and risk["basis"]
        and risk["coverage"]["US100A1"]["disclosed"] == 1
    )
    assert "E3" in risk["uncovered_elements"]
    assert client.get(f"{base}/risk", headers=auth["analyst"]).status_code == 404

    report = client.get(f"{base}/report", headers=attorney).json()
    content = report["content"]
    assert report["version"] == 1 and report["state"] == "draft"
    assert content["generated_by"] == "LLM-assisted summary" and content["llm"] == {"used": True}
    assert [r["patent_id"] for r in content["closest_references"]][0] == "US100A1"
    assert len(content["charts"]) == 3 and content["claim_drafting_considerations"]
    assert content["risk"]["level"] == case["risk_level"]

    # the review workflow continues from the generated report
    assert (
        client.post(f"{base}/review/submit", json={}, headers=attorney).json()["state"]
        == "in_review"
    )
    approved = client.post(f"{base}/review/approve", json={}, headers=attorney).json()
    assert approved["approval"]["content_hash"] == report["content_hash"]

    # export: JSON, and PDF through the HTML renderer
    monkeypatch.setattr(
        export_service, "html_to_pdf", lambda html: b"%PDF-1.7 " + html.encode()[:40]
    )
    pdf = client.post(f"{base}/report/export?format=pdf", headers=attorney)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF") and ".pdf" in pdf.headers["content-disposition"]
    with engine.connect() as conn:
        formats = [
            r[0]["format"]
            for r in conn.execute(text("SELECT detail FROM audit_log WHERE action = 'export'"))
        ]
    assert formats == ["pdf"]


def test_a_second_run_of_the_same_case_adds_no_llm_cost(
    client, auth, seeded, llm, app, settings, engine
):
    attorney = auth["attorney"]
    case_id = new_case(client, attorney, ELEMENTS, priority_date=PRIORITY.isoformat())
    base = f"{API}/cases/{case_id}"
    client.post(f"{base}/run", headers=attorney)
    worker_tick(app, settings)
    with engine.connect() as conn:
        first = conn.execute(
            text(
                "SELECT count(*), COALESCE(sum(tokens_in + tokens_out), 0) FROM llm_calls "
                "WHERE NOT cache_hit"
            )
        ).one()
    assert first[0] >= 2 and first[1] > 0

    assert client.post(f"{base}/run", headers=attorney).status_code == 202  # allowed again
    worker_tick(app, settings)
    with engine.connect() as conn:
        second = conn.execute(
            text(
                "SELECT count(*), COALESCE(sum(tokens_in + tokens_out), 0) FROM llm_calls "
                "WHERE NOT cache_hit"
            )
        ).one()
        cache_rows = conn.execute(
            text("SELECT count(*) FROM llm_calls WHERE cache_hit")
        ).scalar_one()
        statuses = conn.execute(text("SELECT status FROM jobs ORDER BY created_at")).scalars().all()
    assert second == first  # not one extra token, not one extra provider call
    assert cache_rows >= 1 and statuses == ["succeeded", "succeeded"]
    assert client.get(f"{base}/report", headers=attorney).json()["version"] == 1  # no new version


# ---- export ----------------------------------------------------------------------------------------


def test_pdf_export_reports_unavailable_renderer_and_json_still_works(client, auth, monkeypatch):
    attorney = auth["attorney"]
    case_id = new_case(client, attorney, ELEMENTS)
    client.post(f"{API}/cases/{case_id}/report", headers=attorney)

    def missing(html):
        raise export_service.PdfUnavailable("no pango")

    monkeypatch.setattr(export_service, "html_to_pdf", missing)
    unavailable = client.post(f"{API}/cases/{case_id}/report/export?format=pdf", headers=attorney)
    assert unavailable.status_code == 503 and "not available" in unavailable.json()["detail"]
    assert client.post(f"{API}/cases/{case_id}/report/export", headers=attorney).status_code == 200


def test_pdf_export_renders_the_report_html_for_every_state(client, auth, users, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        export_service, "html_to_pdf", lambda html: captured.setdefault("html", html).encode()
    )
    attorney = auth["attorney"]
    case_id = new_case(client, attorney, ELEMENTS)
    client.post(f"{API}/cases/{case_id}/report", headers=attorney)
    client.post(f"{API}/cases/{case_id}/shares", headers=attorney,
                json={"user_id": str(users["viewer"].id), "permission": "read"})  # fmt: skip
    response = client.post(
        f"{API}/cases/{case_id}/report/export?format=pdf", headers=auth["viewer"]
    )
    assert response.status_code == 200  # read access is enough to export
    html = captured["html"]
    assert (
        "Machine summary, no LLM" in html and "Not approved" in html and "API pipeline case" in html
    )
    assert (
        client.post(
            f"{API}/cases/{case_id}/report/export?format=pdf", headers=auth["analyst"]
        ).status_code
        == 404
    )
