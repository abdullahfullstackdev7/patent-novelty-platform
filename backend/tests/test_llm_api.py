"""LLM mode, admin settings, quota view and breaker reset over HTTP."""

from __future__ import annotations

import pytest
from sqlalchemy import text

API = "/api/v1"
VALID = {
    "mode": "groq",
    "groq_model": "openai/gpt-oss-20b",
    "gemini_model": "gemini-3.1-flash-lite",
}


@pytest.fixture(autouse=True)
def clean_llm(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE llm_calls, llm_cache, app_settings"))


def test_mode_endpoint_needs_login_and_reports_provider_availability(client, auth):
    assert client.get(f"{API}/llm/mode").status_code == 401
    body = client.get(f"{API}/llm/mode", headers=auth["viewer"]).json()
    # the test app has no API keys, so no provider can answer
    assert body == {
        "mode": "auto",
        "providers_configured": {"groq": False, "gemini": False},
        "llm_available": False,
    }
    assert "key" not in str(body).lower().replace("providers_configured", "")


def test_status_shows_quota_meters_and_breaker_state_to_admins_only(client, auth):
    status = client.get(f"{API}/admin/llm/status", headers=auth["admin"]).json()
    assert status["mode"] == "auto"
    groq, gemini = status["providers"]
    assert (groq["name"], gemini["name"]) == ("groq", "gemini")
    assert groq["breaker"]["state"] == "closed" and groq["configured"] is False
    assert groq["day"]["tokens_limit"] == 200_000 and groq["minute"]["tokens_limit"] == 8000
    assert gemini["day"]["requests_limit"] == 250
    for role in ("attorney", "analyst", "viewer"):
        assert client.get(f"{API}/admin/llm/status", headers=auth[role]).status_code == 403


def test_settings_can_be_read_changed_and_are_audited(client, auth, engine):
    before = client.get(f"{API}/admin/llm/settings", headers=auth["admin"]).json()
    assert before["mode"] == "auto" and before["defaults"]["groq_model"] == "openai/gpt-oss-20b"

    saved = client.put(f"{API}/admin/llm/settings", json=VALID, headers=auth["admin"])
    assert saved.status_code == 200 and saved.json()["mode"] == "groq"
    assert client.get(f"{API}/llm/mode", headers=auth["viewer"]).json()["mode"] == "groq"
    assert client.get(f"{API}/admin/llm/settings", headers=auth["admin"]).json()["mode"] == "groq"

    changed = {**VALID, "mode": "local_only", "groq_model": "openai/gpt-oss-120b"}
    client.put(f"{API}/admin/llm/settings", json=changed, headers=auth["admin"])
    mode = client.get(f"{API}/llm/mode", headers=auth["viewer"]).json()
    assert mode["mode"] == "local_only" and mode["llm_available"] is False

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT detail FROM audit_log WHERE action = 'llm_settings_change' ORDER BY id")
        ).all()
    assert rows[0][0]["mode"] == "auto -> groq"
    assert rows[1][0]["groq_model"] == "openai/gpt-oss-20b -> openai/gpt-oss-120b"


@pytest.mark.parametrize(
    "bad",
    [
        {**VALID, "mode": "skynet"},
        {**VALID, "gemini_model": "gemini-2.5-flash"},
        {**VALID, "gemini_model": "gemini-2.5-flash-lite"},
        {**VALID, "groq_model": "bad model!"},
        {**VALID, "groq_model": ""},
        {**VALID, "groq_model": "x" * 101},
        {**VALID, "extra": "field"},
        {"mode": "auto"},
    ],
)
def test_invalid_settings_are_rejected(client, auth, bad):
    assert (
        client.put(f"{API}/admin/llm/settings", json=bad, headers=auth["admin"]).status_code == 422
    )
    assert client.get(f"{API}/admin/llm/settings", headers=auth["admin"]).json()["mode"] == "auto"


def test_only_admins_change_settings_or_reset_breakers(client, auth):
    for role in ("attorney", "analyst", "viewer"):
        put = client.put(f"{API}/admin/llm/settings", json=VALID, headers=auth[role])
        assert put.status_code == 403
        assert client.post(f"{API}/admin/llm/breakers/reset", headers=auth[role]).status_code == 403
    assert client.get(f"{API}/admin/llm/settings", headers=auth["admin"]).json()["mode"] == "auto"


def test_breakers_can_be_reset_and_the_reset_is_audited(client, auth, app, engine):
    breaker = app.state.llm_gateway.breakers["groq"]
    for _ in range(3):
        breaker.record_failure()
    opened = client.get(f"{API}/admin/llm/status", headers=auth["admin"]).json()["providers"][0]
    assert opened["breaker"]["state"] == "open" and opened["breaker"]["retry_in_seconds"] > 0

    assert client.post(f"{API}/admin/llm/breakers/reset", headers=auth["admin"]).status_code == 204
    closed = client.get(f"{API}/admin/llm/status", headers=auth["admin"]).json()["providers"][0]
    assert closed["breaker"]["state"] == "closed"
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM audit_log WHERE action = 'llm_breaker_reset'")
            ).scalar_one()
            == 1
        )


def test_per_case_mode_is_stored_on_the_case(client, auth):
    case = client.post(f"{API}/cases", json={"title": "t", "llm_mode": "local_only"},
                       headers=auth["attorney"]).json()  # fmt: skip
    assert case["llm_mode"] == "local_only"
    patched = client.patch(f"{API}/cases/{case['id']}", json={"llm_mode": "gemini"},
                           headers=auth["attorney"])  # fmt: skip
    assert patched.json()["llm_mode"] == "gemini"
