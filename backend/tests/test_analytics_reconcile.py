"""The analytics API against the database: every dashboard number has an independent SQL check.

A fixed-seed history (24 months, 20 clients) is generated per test, so figures are reproducible.
"""

from __future__ import annotations

import time
from datetime import date

import pytest
from sqlalchemy import text

from app.billing.seed import SeedConfig, purge_demo_data, seed_business_data

API = "/api/v1/analytics"
AS_OF = date(2026, 3, 1)  # history covers 2024-03 to 2026-02
FROM, TO = "2024-03-01", "2026-02-28"
RANGE = {"from": FROM, "to": TO}
REVENUE_SQL = "i.status IN ('issued', 'paid', 'overdue')"


@pytest.fixture
def history(auth, session_factory, settings):
    """Depends on `auth` so the clean_db truncate has already run before the history is created."""
    seed_business_data(session_factory, settings, SeedConfig(clients=20, months=24, as_of=AS_OF))
    with session_factory() as s:
        s.execute(text("ANALYZE"))
        s.commit()
    return session_factory


def scalar(sessions, sql: str, **params):
    with sessions() as s:
        return s.execute(text(sql), params).scalar_one()


def get(client, auth, path: str, **params):
    response = client.get(f"{API}{path}", params={**RANGE, **params}, headers=auth["admin"])
    assert response.status_code == 200, (path, response.text)
    return response.json()


def test_revenue_equals_invoice_lines_and_its_three_parts(client, auth, history):
    total = get(client, auth, "/revenue/timeseries", metric="revenue", granularity="month")
    sql_total = float(scalar(history, f"""
        SELECT COALESCE(sum(i.total), 0) FROM invoices i
        WHERE {REVENUE_SQL} AND i.period_start >= :a AND i.period_start <= :b""", a=FROM, b=TO))
    lines_total = float(scalar(history, f"""
        SELECT COALESCE(sum(l.amount), 0) FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id
        WHERE {REVENUE_SQL} AND i.period_start >= :a AND i.period_start <= :b""", a=FROM, b=TO))
    api_total = sum(r["value"] for r in total["rows"])
    assert len(total["rows"]) == 24
    assert api_total == pytest.approx(sql_total, abs=0.01)
    assert lines_total == pytest.approx(sql_total, abs=0.01)  # invoice totals are the sum of their lines

    parts = {m: get(client, auth, "/revenue/timeseries", metric=m, granularity="month")["rows"]
             for m in ("subscription_revenue", "addon_revenue", "overage_revenue")}
    for i, row in enumerate(total["rows"]):
        assert sum(parts[m][i]["value"] for m in parts) == pytest.approx(row["value"], abs=0.01), row["period"]

    for by in ("plan", "industry", "client"):
        breakdown = get(client, auth, "/revenue/breakdown", by=by)
        assert breakdown["meta"]["total"] == pytest.approx(sql_total, abs=0.05), by
        assert sum(r["revenue"] for r in breakdown["rows"]) == pytest.approx(sql_total, abs=0.05), by
        assert sum(r["share_pct"] for r in breakdown["rows"]) == pytest.approx(100, abs=0.2), by


def test_mrr_walk_adds_up_and_matches_the_subscriptions(client, auth, history):
    walk = get(client, auth, "/revenue/mrr-walk")["rows"]
    assert len(walk) == 24
    for earlier, later in zip(walk, walk[1:], strict=False):
        assert later["opening"] == pytest.approx(earlier["closing"], abs=0.01)
    for r in walk:
        moved = r["opening"] + r["new"] + r["expansion"] - r["contraction"] - r["churn"]
        assert moved == pytest.approx(r["closing"], abs=0.01), r["month"]
        assert min(r["new"], r["expansion"], r["contraction"], r["churn"]) >= 0

    mrr = get(client, auth, "/revenue/timeseries", metric="mrr", granularity="month")["rows"]
    assert [round(r["value"], 2) for r in mrr] == [round(r["closing"], 2) for r in walk]
    active_sql = int(scalar(history, """
        SELECT count(DISTINCT client_id) FROM subscriptions
        WHERE started_on <= DATE '2026-02-28' AND (ended_on IS NULL OR ended_on > DATE '2026-02-28')"""))
    assert walk[-1]["active_clients"] == active_sql

    summary = get(client, auth, "/revenue/summary", as_of=TO)
    assert summary["kpis"]["mrr"]["value"] == pytest.approx(walk[-1]["closing"], abs=0.01)
    assert summary["kpis"]["arr"]["value"] == pytest.approx(12 * walk[-1]["closing"], abs=0.1)
    assert summary["kpis"]["arpa"]["value"] == pytest.approx(walk[-1]["closing"] / active_sql, abs=0.02)
    assert len(summary["kpis"]["mrr"]["sparkline"]) == 13


def test_receivables_aging_and_collections_match_sql(client, auth, history):
    aging = get(client, auth, "/revenue/aging", as_of=TO)
    unpaid = float(scalar(history, f"""
        SELECT COALESCE(sum(i.total), 0) FROM invoices i
        WHERE {REVENUE_SQL} AND i.issued_on <= :d AND (i.paid_on IS NULL OR i.paid_on > :d)""", d=TO))
    assert aging["meta"]["outstanding"] == pytest.approx(unpaid, abs=0.01)
    assert sum(r["amount"] for r in aging["rows"]) == pytest.approx(unpaid, abs=0.01)
    assert [r["bucket"] for r in aging["rows"]] == ["current", "1-30", "31-60", "60+"]
    by_status = {s["status"]: s for s in aging["statuses"]}
    for status, row in by_status.items():
        count = int(scalar(history, "SELECT count(*) FROM invoices WHERE status = :s", s=status))
        assert row["invoices"] == count, status

    summary = get(client, auth, "/revenue/summary", as_of=TO)
    assert summary["kpis"]["receivables"]["value"] == pytest.approx(unpaid, abs=0.01)
    paid = float(scalar(history, f"""
        SELECT COALESCE(sum(i.total) FILTER (WHERE i.paid_on IS NOT NULL AND i.paid_on <= :d), 0)
               / NULLIF(sum(i.total), 0) * 100
        FROM invoices i WHERE {REVENUE_SQL} AND i.issued_on <= :d""", d=TO))
    assert 0 < summary["kpis"]["collections_rate"]["value"] <= 100
    assert abs(summary["kpis"]["collections_rate"]["value"] - paid) < 5  # same idea, slightly different month basis


def test_cohorts_cover_every_client_once(client, auth, history):
    cohorts = get(client, auth, "/revenue/cohorts")
    clients_with_subscription = int(scalar(history, "SELECT count(DISTINCT client_id) FROM subscriptions"))
    assert sum(m["size"] for m in cohorts["matrix"]) == clients_with_subscription
    for row in cohorts["matrix"]:
        assert row["retention"]["0"] == 100.0
        assert all(0 <= v <= 100 for v in row["retention"].values() if v is not None)


def test_filters_change_every_series_and_agree_with_sql(client, auth, history):
    base = get(client, auth, "/revenue/breakdown", by="plan")
    starter = next(r for r in base["rows"] if r["key"] == "starter")
    only = get(client, auth, "/revenue/breakdown", by="plan", plan="starter")
    assert [r["key"] for r in only["rows"]] == ["starter"]
    assert only["rows"][0]["revenue"] == pytest.approx(starter["revenue"], abs=0.01)
    assert only["meta"]["total"] < base["meta"]["total"]

    top = get(client, auth, "/revenue/breakdown", by="client")["rows"][0]
    one = get(client, auth, "/revenue/timeseries", metric="revenue", granularity="month", client_id=top["key"])
    sql_one = float(scalar(history, f"""
        SELECT COALESCE(sum(i.total), 0) FROM invoices i WHERE {REVENUE_SQL} AND i.client_id = CAST(:c AS uuid)
          AND i.period_start >= :a AND i.period_start <= :b""", c=top["key"], a=FROM, b=TO))
    assert sum(r["value"] for r in one["rows"]) == pytest.approx(sql_one, abs=0.01)
    assert sum(r["value"] for r in one["rows"]) == pytest.approx(top["revenue"], abs=0.01)

    assert sum(r["value"] for r in get(client, auth, "/revenue/timeseries", metric="revenue", granularity="month", include_demo="false")["rows"]) == 0
    assert get(client, auth, "/ops/funnel", include_demo="false")["rows"][0]["cases"] == 0
    assert sum(r["value"] for r in get(client, auth, "/ops/timeseries", metric="cases_created", granularity="month", plan="starter")["rows"]) > 0

    half = get(client, auth, "/revenue/timeseries", metric="revenue", granularity="month", **{"from": "2025-03-01"})
    assert len(half["rows"]) == 12


def test_compare_to_previous_period_aligns_buckets(client, auth, history):
    data = get(client, auth, "/revenue/timeseries", metric="revenue", granularity="month", compare="previous", **{"from": "2025-03-01"})
    rows = data["rows"]
    assert len(rows) == 12 and rows[0]["previous_period"] == "2024-03-01"
    earlier = get(client, auth, "/revenue/timeseries", metric="revenue", granularity="month", **{"from": "2024-03-01", "to": "2025-02-28"})["rows"]
    assert [r["previous"] for r in rows] == [r["value"] for r in earlier]


def test_granularity_changes_the_bucket_count_but_not_the_total(client, auth, history):
    month = get(client, auth, "/revenue/timeseries", metric="reports_generated", granularity="month", **{"from": "2025-09-01", "to": "2025-11-30"})["rows"]
    week = get(client, auth, "/revenue/timeseries", metric="reports_generated", granularity="week", **{"from": "2025-09-01", "to": "2025-11-30"})["rows"]
    day = get(client, auth, "/revenue/timeseries", metric="reports_generated", granularity="day", **{"from": "2025-09-01", "to": "2025-11-30"})["rows"]
    assert (len(month), len(day)) == (3, 91) and 13 <= len(week) <= 14
    totals = [sum(r["value"] for r in rows) for rows in (month, week, day)]
    assert totals[0] == totals[1] == totals[2] > 0
    sql = int(scalar(history, """
        SELECT count(*) FROM usage_events WHERE event_type = 'report_generated'
          AND occurred_at >= DATE '2025-09-01' AND occurred_at < DATE '2025-12-01'"""))
    assert totals[0] == sql

    bad = client.get(f"{API}/revenue/timeseries", params={**RANGE, "metric": "mrr", "granularity": "day"}, headers=auth["admin"])
    assert bad.status_code == 422 and "month" in bad.text


def test_operations_numbers_match_the_cases_table(client, auth, history):
    created = get(client, auth, "/ops/timeseries", metric="cases_created", granularity="month")["rows"]
    sql_cases = int(scalar(history, "SELECT count(*) FROM cases WHERE created_at >= DATE '2024-03-01' AND created_at < DATE '2026-03-01'"))
    assert sum(r["value"] for r in created) == sql_cases

    funnel = [r["cases"] for r in get(client, auth, "/ops/funnel")["rows"]]
    assert funnel[0] == sql_cases and funnel == sorted(funnel, reverse=True)

    risk = get(client, auth, "/ops/risk")["rows"]
    risk_total = sum(sum(r[k] for k in ("low", "medium", "medium_high", "high")) for r in risk)
    assert risk_total == int(scalar(history, """
        SELECT count(*) FROM cases WHERE risk_level IS NOT NULL
          AND created_at >= DATE '2024-03-01' AND created_at < DATE '2026-03-01'"""))

    turn = get(client, auth, "/ops/turnaround")
    assert sum(r["cases"] for r in turn["rows"]) == turn["summary"]["cases"] > 0
    assert turn["summary"]["p50_hours"] <= turn["summary"]["p90_hours"]
    lat = get(client, auth, "/ops/latency")["rows"]
    assert all(r["p50_ms"] <= r["p95_ms"] for r in lat)

    cpc = get(client, auth, "/ops/cpc", limit=5)
    assert len(cpc["rows"]) <= 5 and cpc["heatmap"]
    assert sum(1 for r in get(client, auth, "/ops/attorneys")["rows"] if r["cases"] > 0) > 0


def test_llm_and_margin_numbers(client, auth, history):
    tokens = get(client, auth, "/llm/tokens", granularity="month")["rows"]
    sql_tokens = int(scalar(history, """
        SELECT COALESCE(sum(tokens_in + tokens_out), 0) FROM llm_calls
        WHERE provider IN ('groq', 'gemini') AND created_at >= DATE '2024-03-01' AND created_at < DATE '2026-03-01'"""))
    api_tokens = sum(r["tokens"] for r in tokens if r["provider"] in ("groq", "gemini"))
    assert api_tokens == sql_tokens

    eff = get(client, auth, "/llm/efficiency")
    assert eff["meta"]["target_tokens_per_case"] == 9000 and eff["rows"]
    assert all(0 <= r["cache_hit_rate"] <= 100 and 0 <= r["fallback_rate"] <= 100 for r in eff["rows"])
    assert "quota" in eff

    margin = get(client, auth, "/revenue/margin")["rows"]
    revenue = {r["period"][:7]: r["value"] for r in get(client, auth, "/revenue/timeseries", metric="revenue", granularity="month")["rows"]}
    for r in margin:
        assert r["revenue"] == pytest.approx(revenue[r["month"][:7]], abs=0.01)
        assert r["gross_margin"] == pytest.approx(r["revenue"] - r["token_cost"] - r["infra_cost"], abs=0.02)
    cost = get(client, auth, "/llm/cost")["rows"]
    assert all(r["cost"] >= 0 and r["revenue_per_case"] >= 0 for r in cost)


def test_csv_export_matches_the_json_rows(client, auth, history):
    for path, params in (("/revenue/timeseries", {"metric": "revenue", "granularity": "month"}), ("/revenue/breakdown", {"by": "plan"}), ("/ops/funnel", {}), ("/llm/efficiency", {})):
        as_json = get(client, auth, path, **params)
        response = client.get(f"{API}{path}", params={**RANGE, **params, "format": "csv"}, headers=auth["admin"])
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv"), path
        assert "attachment" in response.headers["content-disposition"]
        lines = response.text.strip().splitlines()
        assert len(lines) == len(as_json["rows"]) + 1, path


def test_every_endpoint_answers_inside_the_time_budget(client, auth, history):
    """Each query under 300 ms (best of two, to ignore a noisy first call) and the whole dashboard under 2 s."""
    calls = [
        ("/revenue/summary", {"as_of": TO}), ("/revenue/timeseries", {"metric": "revenue", "granularity": "month", "compare": "previous"}),
        ("/revenue/timeseries", {"metric": "mrr_growth_ma3", "granularity": "month"}),
        ("/revenue/breakdown", {"by": "plan"}), ("/revenue/breakdown", {"by": "industry"}), ("/revenue/breakdown", {"by": "client"}),
        ("/revenue/mrr-walk", {}), ("/revenue/aging", {"as_of": TO}), ("/revenue/cohorts", {}), ("/revenue/margin", {}),
        ("/ops/timeseries", {"metric": "cases_created", "granularity": "month"}), ("/ops/funnel", {}), ("/ops/risk", {}),
        ("/ops/cpc", {"limit": 12}), ("/ops/turnaround", {}), ("/ops/attorneys", {}), ("/ops/latency", {}), ("/ops/backlog", {}),
        ("/llm/tokens", {"granularity": "month"}), ("/llm/efficiency", {}), ("/llm/cost", {}),
    ]
    slowest, total = 0.0, 0.0
    for path, params in calls:
        best = float("inf")
        for _ in range(2):
            start = time.perf_counter()
            get(client, auth, path, **params)
            best = min(best, time.perf_counter() - start)
        slowest, total = max(slowest, best), total + best
        assert best < 0.3, f"{path} took {best * 1000:.0f} ms"
    assert total < 2.0, f"dashboard queries took {total:.2f} s in total (slowest {slowest * 1000:.0f} ms)"


def test_notes_flag_demo_data_and_the_seed_is_deterministic(client, auth, history, session_factory, settings):
    meta = get(client, auth, "/revenue/summary", as_of=TO)["meta"]
    assert meta["includes_demo"] is True and meta["demo_through"]

    first = get(client, auth, "/revenue/breakdown", by="plan")["meta"]["total"]
    with session_factory() as s:
        purge_demo_data(s)
        s.commit()
    assert get(client, auth, "/revenue/breakdown", by="plan")["meta"]["total"] == 0
    seed_business_data(session_factory, settings, SeedConfig(clients=20, months=24, as_of=AS_OF))
    assert get(client, auth, "/revenue/breakdown", by="plan")["meta"]["total"] == first
