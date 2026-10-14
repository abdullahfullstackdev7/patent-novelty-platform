"""Public website endpoints: plans, corpus figures and the contact form."""

from __future__ import annotations

import pytest
from sqlalchemy import text

GOOD = {
    "name": "Dana Whitfield",
    "email": "Dana@Example.com",
    "organization": "Whitfield IP",
    "topic": "demo",
    "message": "We would like a walkthrough of claim charting for our team.",
}


@pytest.fixture(autouse=True)
def _empty_inbox(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE contact_messages"))


def rows(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT name, email, topic, ip_address FROM contact_messages")).all()


def test_plans_are_public_ordered_by_price_and_cacheable(client):
    response = client.get("/api/v1/public/plans")
    assert response.status_code == 200
    plans = response.json()
    assert [p["code"] for p in plans] == ["starter", "professional", "enterprise"]
    prices = [float(p["monthly_price"]) for p in plans]
    assert prices == sorted(prices) and prices[0] > 0
    assert {"included_reports", "overage_price", "seats", "extra_seat_price"} <= set(plans[0])
    assert "max-age" in response.headers["cache-control"]


def test_stats_report_the_real_corpus_size(client, seeded, session_factory):
    body = client.get("/api/v1/public/stats").json()
    with session_factory() as s:
        expected = s.execute(text("SELECT count(*) FROM patents")).scalar_one()
    assert body["patents"] == expected and body["chunks"] >= 0
    assert set(body["sources"]) <= {"PV_GRANT", "HUPD_APP"}


def test_contact_form_stores_the_message(client, engine):
    response = client.post("/api/v1/public/contact", json=GOOD)
    assert response.status_code == 202 and response.json() == {"received": True}
    stored = rows(engine)
    assert len(stored) == 1
    assert stored[0].email == "dana@example.com" and stored[0].topic == "demo" and stored[0].ip_address


def test_contact_form_validates_input(client, engine):
    bad = [
        {**GOOD, "email": "not-an-email"},
        {**GOOD, "message": "short"},
        {**GOOD, "name": "   "},
        {**GOOD, "topic": "spam"},
        {**GOOD, "name": "Bob\x00"},
        {**GOOD, "message": "x" * 4001},
        {**GOOD, "extra": "field"},
    ]
    for payload in bad:
        assert client.post("/api/v1/public/contact", json=payload).status_code == 422, payload
    assert rows(engine) == []


def test_honeypot_answers_like_success_but_stores_nothing(client, engine):
    response = client.post("/api/v1/public/contact", json={**GOOD, "website": "http://spam.example"})
    assert response.status_code == 202 and rows(engine) == []


def test_contact_form_is_rate_limited(client, engine):
    codes = [client.post("/api/v1/public/contact", json=GOOD).status_code for _ in range(7)]
    assert codes[:5] == [202] * 5 and codes[5:] == [429, 429]
    assert len(rows(engine)) == 5
