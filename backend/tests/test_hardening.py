"""HTTP hardening: headers, CORS, docs exposure, limits, error handling and log hygiene."""

from __future__ import annotations

import logging

import pytest
from conftest import PASSWORD, ROLE_USERS, TEST_ENV
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

API = "/api/v1"
ORIGIN = "https://app.example.test"

EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
}


def assert_secure_headers(response) -> None:
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value, name
    assert "max-age=" in response.headers["strict-transport-security"]
    assert "includeSubDomains" in response.headers["strict-transport-security"]
    policy = response.headers["permissions-policy"]
    assert "camera=()" in policy and "geolocation=()" in policy
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp


def test_security_headers_on_success_client_error_and_not_found(client, auth):
    responses = [
        client.get(f"{API}/health"),
        client.get(f"{API}/auth/me"),  # 401
        client.get(f"{API}/cases/not-a-uuid", headers=auth["viewer"]),  # 422
        client.get(f"{API}/nothing-here"),  # 404
        client.post(f"{API}/auth/login", json={"email": "bad"}),  # 422
    ]
    assert [r.status_code for r in responses] == [200, 401, 422, 404, 422]
    for response in responses:
        assert_secure_headers(response)
    assert responses[1].headers["cache-control"] == "no-store"  # API responses are never cached


def test_documentation_uses_a_wider_csp_but_still_denies_framing(client):
    docs = client.get("/docs")
    assert docs.status_code == 200
    csp = docs.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" in csp and "frame-ancestors 'none'" in csp
    assert client.get("/openapi.json").status_code == 200


def test_production_does_not_expose_openapi_or_docs(settings, session_factory, clean_db):
    production = settings.model_copy(update={"app_env": "production"})
    with TestClient(create_app(production, session_factory), base_url="https://testserver") as prod:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert prod.get(path).status_code == 404
        assert prod.get(f"{API}/health").status_code == 200


def test_openapi_describes_bearer_authentication(client):
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert "/api/v1/cases/{case_id}/run" in schema["paths"]


def test_cors_allows_only_listed_origins_with_credentials(client):
    allowed = client.options(
        f"{API}/auth/login",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )  # fmt: skip
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert_secure_headers(allowed)

    foreign = client.options(
        f"{API}/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in foreign.headers
    simple = client.get(f"{API}/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers
    assert client.get(f"{API}/health", headers={"Origin": ORIGIN}).headers[
        "access-control-allow-origin"] == ORIGIN  # fmt: skip


def test_validation_errors_do_not_echo_submitted_secrets(client):
    secret = "SuperSecretPassw0rd-Echo-Check"
    response = client.post(f"{API}/auth/login", json={"email": "not-an-email", "password": secret})
    assert response.status_code == 422
    assert secret not in response.text
    detail = response.json()["detail"]
    assert detail and set(detail[0]) == {"loc", "msg", "type"}


def test_oversized_bodies_are_rejected_before_parsing(client, auth, settings, monkeypatch):
    big = {"title": "x" * 3_000_000}
    response = client.post(f"{API}/cases", json=big, headers=auth["attorney"])
    assert response.status_code == 413 and response.json() == {"detail": "Request body too large"}
    assert_secure_headers(response)


def test_default_rate_limit_applies_to_every_route(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_default", "3/minute")
    codes = [client.get(f"{API}/health").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert_secure_headers(client.get(f"{API}/health"))


def test_unhandled_errors_return_a_generic_500_with_headers(
    app, session_factory, settings, clean_db
):
    @app.get("/boom")
    def boom():
        raise RuntimeError("database password=SuperSecret123 leaked in trace")

    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as quiet:
        response = quiet.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "SuperSecret123" not in response.text and "Traceback" not in response.text
    assert_secure_headers(response)


def test_login_does_not_log_credentials_or_tokens(client, users, caplog):
    with caplog.at_level(logging.DEBUG):
        ok = client.post(
            f"{API}/auth/login", json={"email": ROLE_USERS["viewer"], "password": PASSWORD}
        )
        client.post(
            f"{API}/auth/login",
            json={"email": ROLE_USERS["viewer"], "password": "Wr0ng-Guess-Entry-1"},
        )
        client.get(
            f"{API}/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}
        )
    text = caplog.text
    for secret in (PASSWORD, "Wr0ng-Guess-Entry-1", ok.json()["access_token"]):
        assert secret not in text


def test_startup_refuses_weak_secrets(session_factory):
    base = Settings(**{k.lower(): v for k, v in TEST_ENV.items()})
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(base.model_copy(update={"jwt_secret": "too-short"}), session_factory)
    with pytest.raises(RuntimeError, match="FERNET_KEY"):
        create_app(base.model_copy(update={"fernet_key": ""}), session_factory)
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        create_app(
            base.model_copy(update={"app_env": "production", "cookie_secure": False}),
            session_factory,
        )


def test_error_responses_are_json_and_not_sniffable(client):
    response = client.get(f"{API}/nothing-here")
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
