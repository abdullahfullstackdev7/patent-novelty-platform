"""Authorization fuzzing, forged-token behaviour at the API, and the rate limit on model-backed routes.

The fuzz sends hostile path parameters, query values and bodies to every operation in the OpenAPI
document as each kind of caller. It never expects a particular success. It expects the server to
refuse what it must refuse and never to fail with a 5xx.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import text

from app.security import tokens

API = "/api/v1"
PAYLOADS = [
    "not-a-uuid",
    str(uuid.UUID(int=0)),
    "../../etc/passwd",
    "' OR 1=1 --",
    "%00%0d%0aSet-Cookie:x=1",
    "9" * 400,
    str(uuid.uuid4()),
]
BODIES = [{}, [], "text", {"a": [1, {"b": None}]}, None, {"title": "x" * 500, "email": "'; DROP TABLE users;--"}]
ADMIN_PREFIXES = ("/admin", "/billing", "/analytics", "/users")
PUBLIC_PREFIXES = ("/health", "/public", "/auth")


def operations(app):
    """(method, path template, query parameter names) for every operation."""
    out = []
    for path, item in app.openapi()["paths"].items():
        for method, operation in item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            queries = [p["name"] for p in operation.get("parameters", []) if p["in"] == "query"]
            out.append((method.upper(), path, queries))
    return out


def fill(path: str, value: str) -> str:
    import re

    return re.sub(r"\{[^}]+\}", lambda _: value, path)


def send(client, method, path, headers, query=None, body=None):
    kwargs = {"headers": headers, "params": query}
    if method in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = body
    return client.request(method, path, **kwargs)


def relative(path: str) -> str:
    return path[len(API):] if path.startswith(API) else path


def test_no_hostile_input_causes_a_server_error_and_anonymous_callers_are_refused(app, client, auth):
    failures = []
    ops = operations(app)
    assert len(ops) > 60
    for method, path, queries in ops:
        rel = relative(path)
        for payload in PAYLOADS[:5]:
            url = fill(path, payload)
            query = {name: payload for name in queries}
            body = BODIES[PAYLOADS.index(payload) % len(BODIES)]
            for identity in ("anonymous", "viewer", "admin"):
                headers = {} if identity == "anonymous" else auth[identity]
                response = send(client, method, url, headers, query, body)
                tag = f"{identity} {method} {url[:70]}"
                if response.status_code >= 500:
                    failures.append(f"{tag} -> {response.status_code}")
                if identity == "anonymous" and not rel.startswith(PUBLIC_PREFIXES) and response.status_code < 400:
                    failures.append(f"{tag} answered {response.status_code} without a login")
                if identity == "viewer" and rel.startswith(ADMIN_PREFIXES) and response.status_code < 400:
                    failures.append(f"{tag} answered {response.status_code} to a viewer")
    assert not failures, "\n".join(failures[:25])


def test_non_admins_never_reach_admin_areas_even_with_valid_requests(client, auth):
    for identity in ("attorney", "analyst", "viewer"):
        for method, path in (
            ("GET", "/users"), ("GET", "/admin/audit"), ("GET", "/billing/clients"), ("GET", "/billing/invoices"),
            ("GET", "/analytics/revenue/summary"), ("GET", "/analytics/llm/cost"), ("GET", "/admin/llm/settings"),
            ("POST", "/admin/retention/purge"), ("POST", "/billing/refresh"),
        ):
            response = client.request(method, f"{API}{path}", headers=auth[identity])
            assert response.status_code == 403, (identity, method, path, response.status_code)


def forged(settings, **claims):
    now = datetime.now(UTC)
    base = {
        "iss": tokens.ISSUER, "sub": str(uuid.uuid4()), "typ": "access", "jti": uuid.uuid4().hex,
        "iat": now, "exp": now + timedelta(minutes=5),
    }  # fmt: skip
    return jwt.encode({**base, **claims}, settings.jwt_secret, algorithm="HS256")


def test_forged_and_stale_tokens_are_refused_by_the_api(client, users, settings):
    viewer = users["viewer"]
    cases = {
        "unknown user": forged(settings),
        "expired": forged(settings, sub=str(viewer.id), exp=datetime.now(UTC) - timedelta(seconds=30)),
        "wrong type": forged(settings, sub=str(viewer.id), typ="refresh"),
        "wrong secret": jwt.encode({"iss": tokens.ISSUER, "sub": str(viewer.id), "typ": "access", "jti": "x",
                                    "exp": datetime.now(UTC) + timedelta(minutes=5)}, "z" * 48, algorithm="HS256"),
        "alg none": jwt.encode({"sub": str(viewer.id), "typ": "access"}, key=None, algorithm="none"),
        "empty bearer": "",
    }  # fmt: skip
    for name, token in cases.items():
        response = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401, name
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Basic Zm9vOmJhcg=="}).status_code == 401


def test_the_role_comes_from_the_database_not_from_the_token(client, users, settings):
    """A correctly signed token that claims admin for a viewer's id still gets viewer rights."""
    token = forged(settings, sub=str(users["viewer"].id), role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get(f"{API}/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["role"] == "viewer"
    assert client.get(f"{API}/admin/audit", headers=headers).status_code == 403


def test_a_deactivated_user_loses_access_with_their_existing_token(client, users, settings, session_factory, auth):
    assert client.get(f"{API}/auth/me", headers=auth["analyst"]).status_code == 200
    with session_factory() as session:
        session.execute(text("UPDATE users SET is_active = false WHERE id = :i"), {"i": users["analyst"].id})
        session.commit()
    assert client.get(f"{API}/auth/me", headers=auth["analyst"]).status_code in (401, 403)


def test_model_backed_routes_are_rate_limited(client, auth, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_llm", "2/minute")
    case_id = uuid.uuid4()
    codes = [client.post(f"{API}/cases/{case_id}/run", headers=auth["attorney"]).status_code for _ in range(4)]
    assert codes[:2] == [404, 404] and codes[2:] == [429, 429]


def test_error_bodies_never_leak_internals(client, auth):
    probes = [
        client.get(f"{API}/cases/{'0' * 40}", headers=auth["admin"]),
        client.post(f"{API}/cases", json={"title": ["x"]}, headers=auth["attorney"]),
        client.get(f"{API}/analytics/revenue/timeseries?metric=drop%20table", headers=auth["admin"]),
        client.patch(f"{API}/chart/cells/not-a-uuid", json={}, headers=auth["attorney"]),
    ]
    for response in probes:
        text = response.text.lower()
        assert response.status_code in (404, 422), response.status_code
        for leak in ("traceback", "sqlalchemy", "psycopg", "select ", ".py\"", "jwt_secret", "fernet"):
            assert leak not in text, (response.url, leak)
