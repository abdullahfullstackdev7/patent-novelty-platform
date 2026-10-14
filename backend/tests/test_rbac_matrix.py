"""Authorization matrix: every role against every endpoint, plus a route coverage check.

Fixture world: an attorney owns the case, the viewer has a read share, the analyst has no access
(so the case must look like it does not exist), the admin sees everything.
"""

from __future__ import annotations

import itertools
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.db.models import ChartCell, ClaimChart, DisclosureElement

API = "/api/v1"
IDENTITIES = ("anonymous", "admin", "attorney", "analyst", "viewer")

DISCLOSURE = {
    "title": "Matrix disclosure",
    "technical_field": "Testing",
    "problem": "Authorization must be verified.",
    "solution": "A table of roles and endpoints.",
    "elements": [{"text": "An element"}, {"text": "Another element"}],
}
UPLOAD = {"file": ("note.md", b"# Notes\nsome text", "text/markdown")}
LLM_SETTINGS = {
    "mode": "auto",
    "groq_model": "openai/gpt-oss-20b",
    "gemini_model": "gemini-3.1-flash-lite",
}


@dataclass
class Row:
    name: str
    method: str
    path: str
    expected: dict[str, int]
    json: Any = None
    params: dict[str, str] | None = None
    files: dict | None = None
    prepare: str | None = None  # name of a World method run before each call


def codes(admin, attorney, analyst, viewer, anonymous=401) -> dict[str, int]:
    return {"anonymous": anonymous, "admin": admin, "attorney": attorney, "analyst": analyst,
            "viewer": viewer}  # fmt: skip


ALL_OK = codes(200, 200, 200, 200, 200)
READ_CASE = codes(200, 200, 404, 200)  # analyst has no access to the case
EDIT_CASE = codes(200, 200, 404, 403)
ADMIN_ONLY = codes(200, 403, 403, 403)

ROWS = [
    Row("health", "GET", "/health", ALL_OK),
    Row("health ready", "GET", "/health/ready", ALL_OK),
    Row("me", "GET", "/auth/me", codes(200, 200, 200, 200)),
    Row("list users", "GET", "/users", ADMIN_ONLY),
    Row("invite user", "POST", "/users/invite", codes(201, 403, 403, 403), prepare="fresh_invite"),
    Row(
        "update user",
        "PATCH",
        "/users/{analyst2_id}",
        codes(200, 403, 403, 403),
        json={"full_name": "Renamed"},
    ),
    Row("reset password", "POST", "/users/{analyst2_id}/reset-password", ADMIN_ONLY),
    Row("list cases", "GET", "/cases", codes(200, 200, 200, 200)),
    Row("create case", "POST", "/cases", codes(201, 201, 201, 403), json={"title": "Created"}),
    Row("get case", "GET", "/cases/{case_id}", READ_CASE),
    Row(
        "patch case",
        "PATCH",
        "/cases/{case_id}",
        EDIT_CASE,
        json={"title": "Renamed"},
        prepare="draft",
    ),
    Row(
        "delete case",
        "DELETE",
        "/cases/{temp_case_id}",
        codes(204, 204, 404, 403),
        prepare="temp_case",
    ),
    Row("list shares", "GET", "/cases/{case_id}/shares", READ_CASE),
    Row(
        "share case",
        "POST",
        "/cases/{case_id}/shares",
        codes(201, 201, 404, 403),
        json={"user_id": "{analyst2_id}", "permission": "read"},
        prepare="unshare",
    ),
    Row(
        "unshare case",
        "DELETE",
        "/cases/{case_id}/shares/{analyst2_id}",
        codes(204, 204, 404, 403),
        prepare="share_analyst2",
    ),
    Row("get disclosure", "GET", "/cases/{case_id}/disclosure", READ_CASE),
    Row(
        "put disclosure",
        "PUT",
        "/cases/{case_id}/disclosure",
        EDIT_CASE,
        json=DISCLOSURE,
        prepare="draft",
    ),
    Row(
        "parse upload", "POST", "/disclosure/parse-upload", codes(200, 200, 200, 403), files=UPLOAD
    ),
    Row("run case", "POST", "/cases/{case_id}/run", codes(202, 202, 404, 403), prepare="idle"),
    Row("progress", "GET", "/cases/{case_id}/progress", READ_CASE, params={"once": "true"}),
    Row("results", "GET", "/cases/{case_id}/results", READ_CASE),
    Row("chart", "GET", "/cases/{case_id}/chart", READ_CASE),
    Row(
        "override cell",
        "PATCH",
        "/chart/cells/{cell_id}",
        codes(403, 200, 404, 403),
        json={"status": "partial", "reason": "Attorney reviewed the passage"},
        prepare="draft",
    ),
    Row(
        "generate report",
        "POST",
        "/cases/{case_id}/report",
        codes(201, 201, 404, 403),
        prepare="draft",
    ),
    Row(
        "edit report",
        "PUT",
        "/cases/{case_id}/report",
        EDIT_CASE,
        json={"content": {"note": "x"}},
        prepare="draft",
    ),
    Row("get report", "GET", "/cases/{case_id}/report", READ_CASE),
    Row(
        "export report",
        "POST",
        "/cases/{case_id}/report/export",
        READ_CASE,
        params={"format": "json"},
    ),
    Row("review events", "GET", "/cases/{case_id}/review", READ_CASE),
    Row(
        "submit review",
        "POST",
        "/cases/{case_id}/review/submit",
        EDIT_CASE,
        json={},
        prepare="draft",
    ),
    Row(
        "approve",
        "POST",
        "/cases/{case_id}/review/approve",
        codes(403, 200, 404, 403),
        json={},
        prepare="in_review",
    ),
    Row(
        "request changes",
        "POST",
        "/cases/{case_id}/review/request-changes",
        codes(403, 200, 404, 403),
        json={"comment": "Please revisit element 2"},
        prepare="in_review",
    ),
    Row(
        "extract elements",
        "POST",
        "/cases/{case_id}/disclosure/extract-elements",
        EDIT_CASE,
        params={"replace": "true"},
        prepare="draft",
    ),
    Row("risk", "GET", "/cases/{case_id}/risk", READ_CASE),
    Row("analytics", "GET", "/analytics/summary", ADMIN_ONLY),
    Row("billing plans", "GET", "/billing/plans", ADMIN_ONLY),
    Row("audit log", "GET", "/admin/audit", ADMIN_ONLY),
    Row("retention purge", "POST", "/admin/retention/purge", ADMIN_ONLY),
    Row("llm mode", "GET", "/llm/mode", codes(200, 200, 200, 200)),
    Row("llm status", "GET", "/admin/llm/status", ADMIN_ONLY),
    Row("llm settings", "GET", "/admin/llm/settings", ADMIN_ONLY),
    Row(
        "llm settings update",
        "PUT",
        "/admin/llm/settings",
        codes(200, 403, 403, 403),
        json=LLM_SETTINGS,
    ),
    Row("llm breaker reset", "POST", "/admin/llm/breakers/reset", codes(204, 403, 403, 403)),
    Row("/analytics/revenue/summary", "GET", "/analytics/revenue/summary", ADMIN_ONLY),
    Row("/analytics/revenue/timeseries", "GET", "/analytics/revenue/timeseries", ADMIN_ONLY),
    Row("/analytics/revenue/breakdown", "GET", "/analytics/revenue/breakdown", ADMIN_ONLY),
    Row("/analytics/revenue/mrr-walk", "GET", "/analytics/revenue/mrr-walk", ADMIN_ONLY),
    Row("/analytics/revenue/aging", "GET", "/analytics/revenue/aging", ADMIN_ONLY),
    Row("/analytics/revenue/cohorts", "GET", "/analytics/revenue/cohorts", ADMIN_ONLY),
    Row("/analytics/revenue/margin", "GET", "/analytics/revenue/margin", ADMIN_ONLY),
    Row("/analytics/ops/timeseries", "GET", "/analytics/ops/timeseries", ADMIN_ONLY),
    Row("/analytics/ops/funnel", "GET", "/analytics/ops/funnel", ADMIN_ONLY),
    Row("/analytics/ops/risk", "GET", "/analytics/ops/risk", ADMIN_ONLY),
    Row("/analytics/ops/cpc", "GET", "/analytics/ops/cpc", ADMIN_ONLY),
    Row("/analytics/ops/turnaround", "GET", "/analytics/ops/turnaround", ADMIN_ONLY),
    Row("/analytics/ops/attorneys", "GET", "/analytics/ops/attorneys", ADMIN_ONLY),
    Row("/analytics/ops/latency", "GET", "/analytics/ops/latency", ADMIN_ONLY),
    Row("/analytics/ops/backlog", "GET", "/analytics/ops/backlog", ADMIN_ONLY),
    Row("/analytics/llm/tokens", "GET", "/analytics/llm/tokens", ADMIN_ONLY),
    Row("/analytics/llm/efficiency", "GET", "/analytics/llm/efficiency", ADMIN_ONLY),
    Row("/analytics/llm/cost", "GET", "/analytics/llm/cost", ADMIN_ONLY),
    Row("billing clients", "GET", "/billing/clients", ADMIN_ONLY),
    Row("billing client", "GET", "/billing/clients/{zero_id}", codes(404, 403, 403, 403)),
    Row("billing invoices", "GET", "/billing/invoices", ADMIN_ONLY),
    Row("billing invoice", "GET", "/billing/invoices/{zero_id}", codes(404, 403, 403, 403)),
]

# Routes that are public by design or only need a valid login. Covered by test_auth_api.
PUBLIC = {
    ("POST", "/auth/login"), ("POST", "/auth/refresh"), ("POST", "/auth/logout"),
    ("POST", "/auth/accept-invite"), ("GET", "/public/plans"), ("GET", "/public/stats"),
    ("POST", "/public/contact"),
}  # fmt: skip
LOGIN_ONLY = {
    ("POST", "/auth/change-password"), ("POST", "/auth/totp/setup"),
    ("POST", "/auth/totp/enable"), ("POST", "/auth/totp/disable"),
}  # fmt: skip


# Billing writes need real ledger state to succeed, so the sweep here only proves who is turned away.
BILLING_WRITES = {
    ("POST", "/billing/clients"), ("PUT", "/billing/clients/{}/subscription"),
    ("DELETE", "/billing/clients/{}/subscription"), ("POST", "/billing/invoices/generate"),
    ("POST", "/billing/invoices/mark-overdue"), ("POST", "/billing/invoices/{}/issue"),
    ("POST", "/billing/invoices/{}/pay"), ("POST", "/billing/invoices/{}/void"),
    ("POST", "/billing/refresh"),
}  # fmt: skip


class World:
    """One case with a disclosure, a report and a chart, plus helpers to reset its state."""

    def __init__(self, client, auth, users, session_factory, settings):
        self.client, self.auth, self.users = client, auth, users
        self.sessions, self.settings = session_factory, settings
        self.counter = itertools.count()
        self.vars: dict[str, str] = {"analyst2_id": str(users["analyst2"].id), "zero_id": str(uuid.UUID(int=0))}

        created = client.post(
            f"{API}/cases", json={"title": "Matrix case"}, headers=auth["attorney"]
        )
        assert created.status_code == 201, created.text
        self.case_id = created.json()["id"]
        self.vars["case_id"] = self.case_id
        r = client.put(
            f"{API}/cases/{self.case_id}/disclosure", json=DISCLOSURE, headers=auth["attorney"]
        )
        assert r.status_code == 200, r.text
        r = client.post(
            f"{API}/cases/{self.case_id}/shares",
            headers=auth["attorney"],
            json={"user_id": str(users["viewer"].id), "permission": "read"},
        )
        assert r.status_code == 201, r.text
        r = client.post(f"{API}/cases/{self.case_id}/report", headers=auth["attorney"])
        assert r.status_code == 201, r.text
        with session_factory() as session:
            element = session.query(DisclosureElement).first()
            chart = ClaimChart(case_id=uuid.UUID(self.case_id), status="done")
            session.add(chart)
            session.flush()
            cell = ChartCell(chart_id=chart.id, element_id=element.id, patent_id="US100A1",
                             status="disclosed", confidence=0.9, method="local")  # fmt: skip
            session.add(cell)
            session.commit()
            self.vars["cell_id"] = str(cell.id)

    # state helpers, run before individual calls
    def _set_state(self, case_status: str, report_state: str, jobs: bool = False) -> None:
        with self.sessions() as session:
            session.execute(text("DELETE FROM jobs"))
            session.execute(text("UPDATE cases SET status = :s WHERE id = :c"),
                            {"s": case_status, "c": self.case_id})  # fmt: skip
            session.execute(text("UPDATE reports SET state = :s WHERE case_id = :c"),
                            {"s": report_state, "c": self.case_id})  # fmt: skip
            session.commit()

    def draft(self) -> None:
        self._set_state("draft", "draft")

    idle = draft

    def in_review(self) -> None:
        self._set_state("in_review", "in_review")

    def unshare(self) -> None:
        with self.sessions() as session:
            session.execute(text("DELETE FROM case_shares WHERE user_id = :u"),
                            {"u": self.vars["analyst2_id"]})  # fmt: skip
            session.commit()

    def share_analyst2(self) -> None:
        self.unshare()
        with self.sessions() as session:
            session.execute(text("INSERT INTO case_shares (case_id, user_id, permission) "
                                 "VALUES (:c, :u, 'read')"),
                            {"c": self.case_id, "u": self.vars["analyst2_id"]})  # fmt: skip
            session.commit()

    def temp_case(self) -> None:
        created = self.client.post(
            f"{API}/cases", json={"title": "Throwaway"}, headers=self.auth["attorney"]
        )
        self.vars["temp_case_id"] = created.json()["id"]
        self.client.post(
            f"{API}/cases/{self.vars['temp_case_id']}/shares",
            headers=self.auth["attorney"],
            json={"user_id": str(self.users["viewer"].id), "permission": "read"},
        )

    def fresh_invite(self) -> None:
        self.vars["unused"] = str(next(self.counter))

    def render(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.format(**self.vars)
        if isinstance(value, dict):
            return {k: self.render(v) for k, v in value.items()}
        return value


def call(world: World, row: Row, identity: str):
    if row.prepare:
        getattr(world, row.prepare)()
    path = API + row.path.format(**world.vars)
    body = world.render(row.json)
    if row.name == "invite user":
        body = {
            "email": f"invitee{next(world.counter)}@example.com",
            "full_name": "Invitee",
            "role": "viewer",
        }
    headers = {} if identity == "anonymous" else world.auth[identity]
    kwargs: dict[str, Any] = {"headers": headers, "params": row.params}
    if row.files is not None:
        kwargs["files"] = row.files
    elif body is not None:
        kwargs["json"] = body
    return world.client.request(row.method, path, **kwargs)


def test_authorization_matrix(client, auth, users, session_factory, settings):
    world = World(client, auth, users, session_factory, settings)
    failures = []
    for row in ROWS:
        for identity in IDENTITIES:
            response = call(world, row, identity)
            expected = row.expected[identity]
            if response.status_code != expected:
                failures.append(
                    f"{identity:<9} {row.method:<6} {row.path:<45} expected {expected} "
                    f"got {response.status_code}: {response.text[:120]}"
                )
    assert not failures, "authorization mismatches:\n" + "\n".join(failures)


def openapi_routes(app) -> set[tuple[str, str]]:
    """(METHOD, normalised path) for every API operation, read from the OpenAPI schema because
    app.routes hides included routers in current FastAPI versions."""

    def norm(path: str) -> str:
        return re.sub(r"\{[^}]+\}", "{}", path)

    return {
        (method.upper(), norm(path.removeprefix(API)))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(API)
        for method in operations
    }


def test_matrix_covers_every_route(app):
    """Adding an endpoint without deciding who may call it fails this test."""

    def norm(path: str) -> str:
        return re.sub(r"\{[^}]+\}", "{}", path)

    routes = openapi_routes(app)
    assert len(routes) >= 48, "route discovery returned too few operations"
    covered = {(row.method, norm(row.path)) for row in ROWS} | PUBLIC | LOGIN_ONLY | BILLING_WRITES
    assert routes - covered == set(), f"routes without a matrix entry: {sorted(routes - covered)}"
    assert covered - routes == set(), f"matrix rows without a route: {sorted(covered - routes)}"


def test_login_only_endpoints_reject_anonymous_callers(client):
    for method, path in sorted(LOGIN_ONLY):
        body = (
            {"current_password": "x", "new_password": "y"}
            if "change" in path
            else (
                {"code": "123456"}
                if "enable" in path
                else {"password": "x"}
                if "disable" in path
                else None
            )
        )
        response = client.request(method, API + path, json=body)
        assert response.status_code == 401, (method, path, response.status_code)


def test_every_non_public_endpoint_rejects_anonymous_callers(app, client):
    """Independent of the table: any operation that is not public answers 401 without a token."""
    public = {API + path for _, path in PUBLIC} | {API + "/health", API + "/health/ready"}
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith(API) or path in public:
            continue
        concrete = re.sub(r"\{[^}]+\}", str(uuid.UUID(int=0)), path)
        for method in operations:
            response = client.request(method.upper(), concrete)
            assert response.status_code == 401, f"{method.upper()} {path} -> {response.status_code}"
            checked += 1
    assert checked >= 30


def test_billing_writes_turn_away_everyone_but_the_admin(client, auth):
    for method, template in sorted(BILLING_WRITES):
        path = API + template.replace("{}", "00000000-0000-0000-0000-000000000000")
        for identity in ("anonymous", "attorney", "analyst", "viewer"):
            headers = {} if identity == "anonymous" else auth[identity]
            response = client.request(method, path, json={}, headers=headers)
            expected = 401 if identity == "anonymous" else 403
            assert response.status_code == expected, (identity, method, template, response.text)
        admin = client.request(method, path, json={}, headers=auth["admin"])
        assert admin.status_code not in (401, 403), (method, template, admin.text)
