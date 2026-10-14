"""Case lifecycle: CRUD, sharing, encrypted disclosure, pipeline endpoints, review, retention."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import ROLE_USERS
from sqlalchemy import text

from app.db.models import (
    ChartCell,
    ClaimChart,
    DisclosureElement,
    Job,
    Plan,
    SearchResult,
    SearchRun,
)
from app.services.reports import DISCLAIMER, canonical_hash

API = "/api/v1"
SENTINEL = "SENTINEL-ZEBRA-4471"
DISCLOSURE = {
    "title": "Thermal runaway detector",
    "technical_field": f"Battery safety {SENTINEL}",
    "problem": f"Detection is too late. {SENTINEL}",
    "solution": f"Measure impedance and gas. {SENTINEL}",
    "elements": [
        {"text": f"Impedance measurement {SENTINEL}"},
        {"text": "Gas sensor"},
        {"text": "Contactor"},
    ],
}


def new_case(client, headers, title="Case under test", **extra) -> str:
    response = client.post(f"{API}/cases", json={"title": title, **extra}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def put_disclosure(client, headers, case_id, body=None):
    return client.put(f"{API}/cases/{case_id}/disclosure", json=body or DISCLOSURE, headers=headers)


def ready_case(client, headers) -> str:
    case_id = new_case(client, headers)
    assert put_disclosure(client, headers, case_id).status_code == 200
    return case_id


def case_status(client, headers, case_id) -> str:
    return client.get(f"{API}/cases/{case_id}", headers=headers).json()["status"]


# ---- CRUD, visibility ---------------------------------------------------------


def test_create_get_patch_and_permissions(client, auth):
    created = client.post(
        f"{API}/cases",
        json={
            "title": "  Padded title  ",
            "priority_date": "2018-03-01",
            "jurisdiction": "us",
            "retention_days": 90,
        },
        headers=auth["attorney"],
    )
    assert created.status_code == 201
    case = created.json()
    assert case["title"] == "Padded title" and case["jurisdiction"] == "US"
    assert case["status"] == "draft" and case["confidential"] is True
    assert case["permissions"] == {"edit": True, "delete": True, "share": True, "review": True}

    patched = client.patch(
        f"{API}/cases/{case['id']}",
        json={"title": "New title", "llm_mode": "local_only"},
        headers=auth["attorney"],
    )
    assert patched.json()["title"] == "New title" and patched.json()["llm_mode"] == "local_only"
    assert (
        client.patch(
            f"{API}/cases/{case['id']}", json={"title": None}, headers=auth["attorney"]
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"{API}/cases/{case['id']}", json={"status": "approved"}, headers=auth["attorney"]
        ).status_code
        == 422
    )  # unknown field

    as_admin = client.get(f"{API}/cases/{case['id']}", headers=auth["admin"]).json()["permissions"]
    assert as_admin == {"edit": True, "delete": True, "share": True, "review": False}


def test_validation_rejects_bad_input(client, auth):
    bad_bodies = [
        {"title": ""},
        {"title": "x" * 301},
        {"title": "ok", "llm_mode": "skynet"},
        {"title": "ok", "retention_days": 0},
        {"title": "ok", "unexpected": 1},
        {"title": "nul\x00byte"},
    ]
    for body in bad_bodies:
        assert (
            client.post(f"{API}/cases", json=body, headers=auth["attorney"]).status_code == 422
        ), body
    assert client.get(f"{API}/cases/not-a-uuid", headers=auth["attorney"]).status_code == 422


def test_list_shows_only_visible_cases_with_filter_and_paging(client, auth, users):
    mine = [new_case(client, auth["attorney"], f"A{i}") for i in range(3)]
    theirs = new_case(client, auth["analyst2"], "Not yours")
    seen = client.get(f"{API}/cases", headers=auth["attorney"]).json()
    assert seen["total"] == 3 and {c["id"] for c in seen["items"]} == set(mine)
    assert {c["id"] for c in client.get(f"{API}/cases", headers=auth["admin"]).json()["items"]} == {
        *mine,
        theirs,
    }
    assert client.get(f"{API}/cases", headers=auth["viewer"]).json()["total"] == 0

    page = client.get(f"{API}/cases?limit=2&offset=2", headers=auth["attorney"]).json()
    assert len(page["items"]) == 1 and page["total"] == 3
    assert client.get(f"{API}/cases?status=approved", headers=auth["attorney"]).json()["total"] == 0
    assert client.get(f"{API}/cases?limit=1000", headers=auth["attorney"]).status_code == 422


def test_invisible_cases_answer_404_for_every_verb(client, auth):
    case_id = ready_case(client, auth["attorney"])
    for method, suffix, body in [
        ("GET", "", None), ("PATCH", "", {"title": "x"}), ("DELETE", "", None),
        ("GET", "/disclosure", None), ("PUT", "/disclosure", DISCLOSURE),
        ("POST", "/run", None), ("GET", "/results", None), ("GET", "/chart", None),
        ("POST", "/report", None), ("GET", "/report", None), ("GET", "/review", None),
        ("GET", "/shares", None), ("GET", "/progress", None),
    ]:  # fmt: skip
        response = client.request(
            method, f"{API}/cases/{case_id}{suffix}", json=body, headers=auth["analyst"]
        )
        assert response.status_code == 404, (method, suffix, response.status_code)
        assert response.json() == {"detail": "Not found"}
    # a case that really does not exist looks exactly the same
    ghost = client.get(f"{API}/cases/{uuid.uuid4()}", headers=auth["analyst"])
    assert ghost.status_code == 404 and ghost.json() == {"detail": "Not found"}


def test_sql_metacharacters_are_data_not_code(client, auth, engine):
    title = "x'); DROP TABLE cases;-- \" OR 1=1"
    case_id = new_case(client, auth["attorney"], title)
    assert client.get(f"{API}/cases/{case_id}", headers=auth["attorney"]).json()["title"] == title
    hostile = client.get(f"{API}/cases", params={"status": "' OR '1'='1"}, headers=auth["attorney"])
    assert hostile.status_code == 200 and hostile.json()["total"] == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM cases")).scalar_one() == 1


# ---- sharing ------------------------------------------------------------------


def test_sharing_grants_the_right_level_of_access(client, auth, users):
    case_id = ready_case(client, auth["attorney"])
    share = lambda who, perm: client.post(  # noqa: E731
        f"{API}/cases/{case_id}/shares",
        json={"user_id": str(users[who].id), "permission": perm},
        headers=auth["attorney"],
    )

    assert client.get(f"{API}/cases/{case_id}", headers=auth["analyst2"]).status_code == 404
    assert share("analyst2", "read").status_code == 201
    assert client.get(f"{API}/cases/{case_id}", headers=auth["analyst2"]).status_code == 200
    assert put_disclosure(client, auth["analyst2"], case_id).status_code == 403  # read only
    assert case_id in {
        c["id"] for c in client.get(f"{API}/cases", headers=auth["analyst2"]).json()["items"]
    }

    assert share("analyst2", "write").status_code == 201  # upgrade in place
    assert put_disclosure(client, auth["analyst2"], case_id).status_code == 200
    assert client.delete(f"{API}/cases/{case_id}", headers=auth["analyst2"]).status_code == 403
    cannot_reshare = client.post(
        f"{API}/cases/{case_id}/shares",
        json={"user_id": str(users["viewer"].id), "permission": "read"},
        headers=auth["analyst2"],
    )
    assert cannot_reshare.status_code == 403

    assert share("viewer", "write").status_code == 400  # viewers are read-only
    assert share("attorney", "read").status_code == 400  # the owner already has access
    ghost = client.post(
        f"{API}/cases/{case_id}/shares",
        json={"user_id": str(uuid.uuid4()), "permission": "read"},
        headers=auth["attorney"],
    )
    assert ghost.status_code == 404

    listed = client.get(f"{API}/cases/{case_id}/shares", headers=auth["attorney"]).json()
    assert [(s["email"], s["permission"]) for s in listed] == [(ROLE_USERS["analyst2"], "write")]
    assert (
        client.delete(
            f"{API}/cases/{case_id}/shares/{users['analyst2'].id}", headers=auth["attorney"]
        ).status_code
        == 204
    )
    assert client.get(f"{API}/cases/{case_id}", headers=auth["analyst2"]).status_code == 404


# ---- disclosure ---------------------------------------------------------------


def test_disclosure_round_trip_is_encrypted_at_rest(client, auth, engine):
    case_id = new_case(client, auth["attorney"])
    assert (
        client.get(f"{API}/cases/{case_id}/disclosure", headers=auth["attorney"]).status_code == 404
    )
    saved = put_disclosure(client, auth["attorney"], case_id)
    assert saved.status_code == 200
    body = saved.json()
    assert body["problem"] == DISCLOSURE["problem"]
    assert [e["id"] for e in body["elements"]] == ["E1", "E2", "E3"]
    assert body["elements"][0]["text"] == DISCLOSURE["elements"][0]["text"]
    assert len(body["content_hash"]) == 64

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT technical_field, problem, solution FROM disclosures")
        ).one()
        element_texts = [r[0] for r in conn.execute(text("SELECT text FROM disclosure_elements"))]
    for value in (*stored, *element_texts):
        assert SENTINEL not in value and value.startswith("gAAAA")
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT title FROM disclosures")).scalar_one() == DISCLOSURE["title"]
        )


def test_disclosure_update_keeps_element_ids_so_chart_cells_survive(client, auth, session_factory):
    case_id = ready_case(client, auth["attorney"])
    with session_factory() as session:
        before = {e.key: e.id for e in session.query(DisclosureElement)}
    changed = {
        **DISCLOSURE,
        "elements": [{"text": "Impedance measurement, revised"}, {"text": "Gas sensor"}],
    }
    assert put_disclosure(client, auth["attorney"], case_id, changed).status_code == 200
    with session_factory() as session:
        after = {e.key: e.id for e in session.query(DisclosureElement)}
    assert after == {k: v for k, v in before.items() if k in ("E1", "E2")}
    got = client.get(f"{API}/cases/{case_id}/disclosure", headers=auth["attorney"]).json()
    assert got["elements"][0]["text"] == "Impedance measurement, revised"


def test_disclosure_hash_is_stable_and_content_sensitive(client, auth):
    a, b = ready_case(client, auth["attorney"]), ready_case(client, auth["attorney"])
    hash_a = client.get(f"{API}/cases/{a}/disclosure", headers=auth["attorney"]).json()[
        "content_hash"
    ]
    hash_b = client.get(f"{API}/cases/{b}/disclosure", headers=auth["attorney"]).json()[
        "content_hash"
    ]
    assert hash_a == hash_b
    put_disclosure(client, auth["attorney"], b, {**DISCLOSURE, "problem": "different"})
    assert (
        client.get(f"{API}/cases/{b}/disclosure", headers=auth["attorney"]).json()["content_hash"]
        != hash_a
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"elements": [{"text": f"e{i}"} for i in range(31)]},
        {"elements": [{"text": ""}]},
        {"elements": [{"text": "x" * 1001}]},
        {"problem": "p" * 8001},
        {"title": "bell\x07char"},
        {"unknown": "field"},
        {"elements": [{"text": "ok", "source": "robot"}]},
    ],
    ids=[
        "31-elements",
        "empty-element",
        "long-element",
        "long-problem",
        "control-char",
        "extra-field",
        "bad-source",
    ],
)
def test_disclosure_validation(client, auth, mutation):
    case_id = new_case(client, auth["attorney"])
    response = put_disclosure(client, auth["attorney"], case_id, {**DISCLOSURE, **mutation})
    assert response.status_code == 422
    assert SENTINEL not in response.text  # validation errors never echo the submitted text


# ---- upload -------------------------------------------------------------------


def upload(client, headers, name="notes.md", content=b"# Title\nBody", ctype="text/markdown"):
    return client.post(
        f"{API}/disclosure/parse-upload", files={"file": (name, content, ctype)}, headers=headers
    )


def test_upload_accepts_text_and_markdown_only(client, auth):
    ok = upload(client, auth["analyst"])
    assert (
        ok.status_code == 200
        and ok.json()["text"] == "# Title\nBody"
        and ok.json()["characters"] == 12
    )
    assert (
        upload(client, auth["analyst"], "n.txt", b"\xef\xbb\xbfplain", "text/plain").json()["text"]
        == "plain"
    )
    assert upload(client, auth["analyst"], "../../etc/notes.md").json()["filename"] == "notes.md"
    assert upload(client, auth["analyst"], "n.pdf", b"%PDF", "application/pdf").status_code == 415
    assert upload(client, auth["analyst"], "n.md", b"x", "application/pdf").status_code == 415
    assert upload(client, auth["analyst"], "n.exe", b"MZ", "text/plain").status_code == 415
    assert upload(client, auth["analyst"], "n.txt", b"bin\x00ary", "text/plain").status_code == 400
    assert (
        upload(client, auth["analyst"], "n.txt", b"\xff\xfe\xfa", "text/plain").status_code == 400
    )
    assert upload(client, auth["viewer"]).status_code == 403


def test_upload_size_limit(client, auth, settings, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    assert upload(client, auth["analyst"], content=b"a" * 100).status_code == 200
    assert upload(client, auth["analyst"], content=b"a" * 101).status_code == 413


# ---- run, progress ------------------------------------------------------------


def test_run_queues_one_job_and_locks_disclosure_edits(client, auth, session_factory):
    empty = new_case(client, auth["attorney"])
    assert client.post(f"{API}/cases/{empty}/run", headers=auth["attorney"]).status_code == 409

    case_id = ready_case(client, auth["attorney"])
    started = client.post(f"{API}/cases/{case_id}/run", headers=auth["attorney"])
    assert started.status_code == 202
    job = started.json()
    assert job["status"] == "queued" and job["kind"] == "pipeline"
    assert case_status(client, auth["attorney"], case_id) == "running"
    assert client.post(f"{API}/cases/{case_id}/run", headers=auth["attorney"]).status_code == 409
    assert put_disclosure(client, auth["attorney"], case_id).status_code == 409
    with session_factory() as session:
        assert session.query(Job).filter(Job.case_id == uuid.UUID(case_id)).count() == 1


def test_llm_endpoints_have_a_stricter_rate_limit(client, auth, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_llm", "2/minute")
    case_id = ready_case(client, auth["attorney"])
    codes = [client.post(f"{API}/cases/{case_id}/run", headers=auth["attorney"]).status_code
             for _ in range(3)]  # fmt: skip
    assert codes == [202, 409, 429]


def test_progress_streams_server_sent_events(client, auth, session_factory):
    case_id = ready_case(client, auth["attorney"])
    idle = client.get(f"{API}/cases/{case_id}/progress", headers=auth["attorney"])
    assert idle.headers["content-type"].startswith("text/event-stream")
    assert idle.headers["cache-control"] == "no-store"
    assert json.loads(idle.text.split("data: ", 1)[1].split("\n", 1)[0])["status"] == "idle"

    client.post(f"{API}/cases/{case_id}/run", headers=auth["attorney"])
    once = client.get(f"{API}/cases/{case_id}/progress?once=true", headers=auth["attorney"])
    event = json.loads(once.text.split("data: ", 1)[1].split("\n", 1)[0])
    assert once.text.startswith("event: status\n")
    assert event["status"] == "queued" and event["case_status"] == "running"
    assert event["tokens_used"] == 0

    with session_factory() as session:  # the worker finishes: the stream must end by itself
        session.query(Job).update({"status": "succeeded"})
        session.commit()
    done = client.get(f"{API}/cases/{case_id}/progress", headers=auth["attorney"])
    assert done.status_code == 200 and '"status": "succeeded"' in done.text


# ---- results and chart --------------------------------------------------------


def test_results_list_the_latest_run_with_patent_details(client, auth, seeded, session_factory):
    case_id = ready_case(client, auth["attorney"])
    assert client.get(f"{API}/cases/{case_id}/results", headers=auth["attorney"]).json() == {
        "run_id": None, "suggested_cpc": [], "results": []}  # fmt: skip
    with session_factory() as session:
        run = SearchRun(
            case_id=uuid.UUID(case_id), suggested_cpc=[{"subclass": "H01M", "votes": 3}]
        )
        session.add(run)
        session.flush()
        session.add_all([
            SearchResult(run_id=run.id, patent_id="US101A1", rank=2, score=0.5, matched_chunk_ids=["a"]),
            SearchResult(run_id=run.id, patent_id="US100A1", rank=1, score=0.9, fused_score=0.1,
                         rerank_score=4.2, matched_chunk_ids=["b", "c"], in_chart=True),
            SearchResult(run_id=run.id, patent_id="US_GONE", rank=3, score=0.1),
        ])  # fmt: skip
        session.commit()
    data = client.get(f"{API}/cases/{case_id}/results", headers=auth["attorney"]).json()
    assert [r["patent_id"] for r in data["results"]] == ["US100A1", "US101A1", "US_GONE"]
    assert data["results"][0]["title"] == "Battery thermal runaway detection"
    assert data["results"][0]["in_chart"] is True and data["results"][0]["matched_chunk_ids"] == [
        "b",
        "c",
    ]
    assert data["results"][2]["title"] is None  # corpus was reloaded, history still renders
    assert data["suggested_cpc"] == [{"subclass": "H01M", "votes": 3}]


def make_chart(session_factory, case_id: str) -> uuid.UUID:
    with session_factory() as session:
        element = session.query(DisclosureElement).filter(DisclosureElement.key == "E1").one()
        chart = ClaimChart(case_id=uuid.UUID(case_id), status="done")
        session.add(chart)
        session.flush()
        cell = ChartCell(chart_id=chart.id, element_id=element.id, patent_id="US100A1",
                         status="not_found", confidence=0.31, method="local", excerpt="x")  # fmt: skip
        session.add(cell)
        session.commit()
        return cell.id


def test_chart_and_attorney_override_keep_the_original_value(client, auth, session_factory):
    case_id = ready_case(client, auth["attorney"])
    empty = client.get(f"{API}/cases/{case_id}/chart", headers=auth["attorney"]).json()
    assert empty["cells"] == [] and len(empty["elements"]) == 3 and empty["chart_status"] is None

    cell_id = make_chart(session_factory, case_id)
    chart = client.get(f"{API}/cases/{case_id}/chart", headers=auth["attorney"]).json()
    assert chart["references"] == ["US100A1"] and chart["cells"][0]["element"] == "E1"
    assert chart["cells"][0]["overridden"] is False

    url = f"{API}/chart/cells/{cell_id}"
    assert (
        client.patch(
            url, json={"status": "disclosed", "reason": "no"}, headers=auth["attorney"]
        ).status_code
        == 422
    )
    first = client.patch(
        url,
        json={"status": "partial", "reason": "Claim 1 recites the sensor"},
        headers=auth["attorney"],
    )
    assert first.status_code == 200 and first.json()["status"] == "partial"
    second = client.patch(
        url,
        json={"status": "disclosed", "reason": "Confirmed on re-read"},
        headers=auth["attorney"],
    ).json()
    assert second["original"]["status"] == "not_found" and second["original"]["method"] == "local"
    assert second["overridden"] is True and second["override_reason"] == "Confirmed on re-read"

    events = client.get(f"{API}/cases/{case_id}/review", headers=auth["attorney"]).json()
    assert [e["event_type"] for e in events] == ["cell_override", "cell_override"]
    assert (
        client.patch(
            url, json={"status": "partial", "reason": "viewer attempt"}, headers=auth["viewer"]
        ).status_code
        == 404
    )  # no access to the case at all


# ---- report and review lifecycle ----------------------------------------------


def test_report_review_approval_lifecycle(
    client, auth, users, engine, session_factory, monkeypatch
):
    attorney = auth["attorney"]
    case_id = ready_case(client, attorney)
    base = f"{API}/cases/{case_id}"

    # submitting without a report is refused
    assert client.post(f"{base}/review/submit", json={}, headers=attorney).status_code == 409
    assert client.put(f"{base}/report", json={"content": {}}, headers=attorney).status_code == 409

    first = client.post(f"{base}/report", headers=attorney)
    assert first.status_code == 201
    v1 = first.json()
    assert v1["version"] == 1 and v1["state"] == "draft" and v1["approval"] is None
    assert v1["content"]["generated_by"] == "Machine summary, no LLM"
    assert v1["content"]["disclaimer"] == DISCLAIMER
    assert [c["element"] for c in v1["content"]["element_coverage"]] == ["E1", "E2", "E3"]
    assert v1["content_hash"] == canonical_hash(v1["content"])

    with engine.connect() as conn:  # the stored report is sealed, not readable JSON
        stored = conn.execute(text("SELECT content::text FROM report_versions")).scalar_one()
    assert SENTINEL not in stored and "ciphertext" in stored and "Impedance" not in stored

    edited = client.put(
        f"{base}/report",
        headers=attorney,
        json={"content": {**v1["content"], "executive_summary": "Edited", "disclaimer": "none"}},
    )
    assert edited.status_code == 200
    v2 = edited.json()
    assert v2["version"] == 2 and v2["content"]["executive_summary"] == "Edited"
    assert v2["content"]["disclaimer"] == DISCLAIMER  # cannot be edited away
    assert [v["version"] for v in v2["versions"]] == [1, 2]
    old = client.get(f"{base}/report?version=1", headers=attorney).json()
    assert old["content"]["executive_summary"] == v1["content"]["executive_summary"]
    assert client.get(f"{base}/report?version=9", headers=attorney).status_code == 404
    assert (
        client.put(
            f"{base}/report", json={"content": {"x": "y" * 250_000}}, headers=attorney
        ).status_code
        == 413
    )

    # submit, then the report is frozen for editing
    assert (
        client.post(f"{base}/review/submit", json={"comment": "Ready"}, headers=attorney).json()[
            "state"
        ]
        == "in_review"
    )
    assert case_status(client, attorney, case_id) == "in_review"
    assert client.post(f"{base}/review/submit", json={}, headers=attorney).status_code == 409
    assert client.put(f"{base}/report", json={"content": {}}, headers=attorney).status_code == 409
    assert client.post(f"{base}/report", headers=attorney).status_code == 409

    # reviewers: admin cannot sign off, comment is mandatory for change requests
    assert client.post(f"{base}/review/approve", json={}, headers=auth["admin"]).status_code == 403
    assert (
        client.post(
            f"{base}/review/request-changes", json={"comment": "x"}, headers=attorney
        ).status_code
        == 422
    )
    sent_back = client.post(
        f"{base}/review/request-changes", json={"comment": "Rework element 2"}, headers=attorney
    )
    assert sent_back.json()["state"] == "changes_requested"
    assert case_status(client, attorney, case_id) == "changes_requested"
    assert (
        client.post(f"{base}/review/approve", json={}, headers=attorney).status_code == 409
    )  # not in review
    v3 = client.put(f"{base}/report", json={"content": v2["content"]}, headers=attorney).json()
    assert v3["version"] == 3

    client.post(f"{base}/review/submit", json={}, headers=attorney)
    approved = client.post(f"{base}/review/approve", json={"comment": "Approved"}, headers=attorney)
    assert approved.status_code == 200
    body = approved.json()
    stamp = body["approval"]
    assert body["state"] == "approved" and stamp["version"] == 3
    assert stamp["approved_by"] == "Attorney Person" and stamp["role"] == "attorney"
    assert stamp["content_hash"] == canonical_hash(body["content"]) == v3["content_hash"]
    assert datetime.fromisoformat(stamp["approved_at"]) > datetime.now(UTC) - timedelta(minutes=1)

    # everything is locked after approval
    cell_id = make_chart(session_factory, case_id)
    locked = [
        client.patch(base, json={"title": "x"}, headers=attorney),
        put_disclosure(client, attorney, case_id),
        client.post(f"{base}/report", headers=attorney),
        client.put(f"{base}/report", json={"content": {}}, headers=attorney),
        client.post(f"{base}/run", headers=attorney),
        client.patch(
            f"{API}/chart/cells/{cell_id}",
            json={"status": "partial", "reason": "late change"},
            headers=attorney,
        ),
        client.post(f"{base}/review/approve", json={}, headers=attorney),
        client.post(f"{base}/review/submit", json={}, headers=attorney),
    ]
    assert [r.status_code for r in locked] == [409] * len(locked)

    # export carries the stamp and is audited, PDF arrives in Phase 5
    exported = client.post(f"{base}/report/export?format=json", headers=auth["admin"])
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    assert exported.json()["approval"]["content_hash"] == stamp["content_hash"]
    monkeypatch.setattr("app.services.export.html_to_pdf", lambda html: b"%PDF-1.7 stub")
    pdf = client.post(f"{base}/report/export?format=pdf", headers=attorney)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert client.post(f"{base}/report/export?format=xml", headers=attorney).status_code == 422

    kinds = [e["event_type"] for e in client.get(f"{base}/review", headers=attorney).json()]
    assert kinds == ["submitted", "changes_requested", "submitted", "approved"]


def test_analyst_prepares_and_a_shared_attorney_approves(client, auth, users):
    case_id = ready_case(client, auth["analyst"])
    base = f"{API}/cases/{case_id}"
    client.post(f"{base}/report", headers=auth["analyst"])
    assert client.post(f"{base}/review/submit", json={}, headers=auth["analyst"]).status_code == 200
    assert (
        client.post(f"{base}/review/approve", json={}, headers=auth["analyst"]).status_code == 403
    )
    assert (
        client.post(f"{base}/review/approve", json={}, headers=auth["attorney"]).status_code == 404
    )

    client.post(
        f"{base}/shares",
        json={"user_id": str(users["attorney"].id), "permission": "read"},
        headers=auth["analyst"],
    )
    assert (
        client.post(f"{base}/review/approve", json={}, headers=auth["attorney"]).json()["state"]
        == "approved"
    )


# ---- delete, retention, admin -------------------------------------------------


def test_hard_delete_removes_everything_for_the_case(
    client, auth, users, seeded, session_factory, engine
):
    attorney = auth["attorney"]
    case_id = ready_case(client, attorney)
    client.post(
        f"{API}/cases/{case_id}/shares",
        headers=attorney,
        json={"user_id": str(users["viewer"].id), "permission": "read"},
    )
    client.post(f"{API}/cases/{case_id}/report", headers=attorney)
    client.post(f"{API}/cases/{case_id}/run", headers=attorney)
    make_chart(session_factory, case_id)
    with session_factory() as session:
        session.add(SearchRun(case_id=uuid.UUID(case_id)))
        session.commit()

    assert client.delete(f"{API}/cases/{case_id}", headers=auth["viewer"]).status_code == 403
    assert client.delete(f"{API}/cases/{case_id}", headers=auth["analyst"]).status_code == 404
    assert client.delete(f"{API}/cases/{case_id}", headers=attorney).status_code == 204
    assert client.get(f"{API}/cases/{case_id}", headers=auth["admin"]).status_code == 404

    with engine.connect() as conn:
        for table in (
            "disclosures",
            "disclosure_elements",
            "case_shares",
            "reports",
            "report_versions",
            "jobs",
            "search_runs",
            "claim_charts",
            "chart_cells",
        ):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
        assert (
            conn.execute(text("SELECT count(*) FROM patents")).scalar_one() == 8
        )  # corpus untouched
        deleted = conn.execute(
            text("SELECT detail::text, entity_id FROM audit_log WHERE action = 'case_delete'")
        ).one()
    assert deleted[1] == case_id and "Case under test" not in deleted[0]


def test_retention_purge_deletes_only_expired_cases(client, auth, engine):
    expired = new_case(client, auth["attorney"], "old", retention_days=1)
    young = new_case(client, auth["attorney"], "young", retention_days=30)
    forever = new_case(client, auth["attorney"], "forever")
    with engine.begin() as conn:
        conn.execute(text("UPDATE cases SET created_at = now() - interval '3 days'"))

    assert client.post(f"{API}/admin/retention/purge", headers=auth["attorney"]).status_code == 403
    purge = client.post(f"{API}/admin/retention/purge", headers=auth["admin"])
    assert purge.status_code == 200 and purge.json() == {"deleted": 1, "case_ids": [expired]}
    remaining = {c["id"] for c in client.get(f"{API}/cases", headers=auth["admin"]).json()["items"]}
    assert remaining == {young, forever}
    assert client.post(f"{API}/admin/retention/purge", headers=auth["admin"]).json()["deleted"] == 0


def test_audit_log_records_security_events_without_content(client, auth, users, engine, caplog):
    attorney, admin = auth["attorney"], auth["admin"]
    case_id = ready_case(client, attorney)
    client.get(f"{API}/cases/{case_id}", headers=attorney)
    client.post(f"{API}/cases/{case_id}/report", headers=attorney)
    client.post(f"{API}/cases/{case_id}/report/export", headers=attorney)
    client.post(f"{API}/cases/{case_id}/review/submit", json={}, headers=attorney)
    client.post(f"{API}/cases/{case_id}/review/approve", json={}, headers=attorney)
    client.patch(f"{API}/users/{users['viewer'].id}", json={"role": "analyst"}, headers=admin)

    rows = client.get(f"{API}/admin/audit?limit=200", headers=admin).json()
    actions = {r["action"] for r in rows}
    assert {"login_success", "case_create", "case_view", "report_generate", "export",
            "review_submit", "approve", "role_change"} <= actions  # fmt: skip
    change = next(r for r in rows if r["action"] == "role_change")
    assert change["user_id"] == str(users["admin"].id) and change["entity_id"] == str(
        users["viewer"].id
    )
    assert change["detail"] == {"from": "viewer", "to": "analyst"}
    assert all(r["ip_address"] == "testclient" and r["created_at"] for r in rows)
    assert SENTINEL not in json.dumps(rows)
    assert (
        client.get(f"{API}/admin/audit?action=approve", headers=admin).json()[0]["action"]
        == "approve"
    )
    assert len(client.get(f"{API}/admin/audit?limit=2", headers=admin).json()) == 2
    assert SENTINEL not in caplog.text

    # plaintext of the disclosure exists nowhere in the database
    with engine.connect() as conn:
        for table, column in (
            ("disclosures", "problem"),
            ("disclosure_elements", "text"),
            ("report_versions", "content::text"),
            ("audit_log", "detail::text"),
        ):
            assert SENTINEL not in " ".join(
                r[0] for r in conn.execute(text(f"SELECT {column} FROM {table}"))
            )


def test_analytics_summary_and_billing_plans(client, auth, session_factory):
    ready_case(client, auth["attorney"])
    summary = client.get(f"{API}/analytics/summary", headers=auth["admin"]).json()
    assert summary["cases_by_status"] == {"draft": 1} and summary["users_by_role"]["attorney"] == 1
    assert summary["reports_approved"] == 0
    with session_factory() as session:
        session.add(Plan(code="trial", name="Trial", monthly_price=490, included_reports=10,
                         overage_price=45, seats=3))  # fmt: skip
        session.commit()
    try:
        plans = client.get(f"{API}/billing/plans", headers=auth["admin"]).json()
        by_code = {p["code"]: p for p in plans}
        assert {"starter", "professional", "enterprise"} <= set(by_code)  # seeded by migration 0007
        assert by_code["trial"]["monthly_price"] == 490.0
    finally:  # the migration's plans are reference data and stay
        with session_factory() as session:
            session.query(Plan).filter(Plan.code == "trial").delete()
            session.commit()
