"""Analytics queries: revenue, operations and LLM efficiency.

Revenue figures come from the materialized views (refresh them after seeding or a billing
change). Operational and LLM figures read the live tables. Every function returns plain rows
(dicts of numbers, dates and strings) that the API renders as JSON or CSV.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.billing.costing import TOKEN_COST_SQL, price_params
from app.billing.subscriptions import month_start, next_month, previous_month
from app.config import Settings

UNITS = ("day", "week", "month")
REVENUE_STATUSES = "('issued', 'paid', 'overdue')"
LLM_OK = "('ok', 'invalid_output')"


@dataclass(frozen=True)
class Filters:
    """The shared filter bar: demo data on or off, one client, one plan."""

    include_demo: bool = True
    client_id: uuid.UUID | None = None
    plan: str | None = None

    def params(self) -> dict[str, Any]:
        return {
            "include_demo": self.include_demo,
            "client_id": str(self.client_id) if self.client_id else None,
            "plan": self.plan,
        }


def demo(alias: str) -> str:
    return f"(:include_demo OR NOT {alias}.is_demo)"


def by_client(column: str) -> str:
    return f"(CAST(:client_id AS uuid) IS NULL OR {column} = CAST(:client_id AS uuid))"


def by_plan(column: str) -> str:
    return f"(CAST(:plan AS text) IS NULL OR {column} = CAST(:plan AS text))"


def num(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def rows(session: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result = session.execute(text(sql), params).mappings().all()
    return [{key: num(value) for key, value in row.items()} for row in result]


# ---- buckets ------------------------------------------------------------------------------------


def bucket_start(day: date, unit: str) -> date:
    if unit == "month":
        return month_start(day)
    if unit == "week":
        return day - timedelta(days=day.weekday())  # PostgreSQL date_trunc('week') starts on Monday
    return day


def bucket_end(bucket: date, unit: str) -> date:
    if unit == "month":
        return next_month(bucket) - timedelta(days=1)
    if unit == "week":
        return bucket + timedelta(days=6)
    return bucket


def step(bucket: date, unit: str, count: int = 1) -> date:
    if unit == "month":
        result = bucket
        for _ in range(abs(count)):
            result = next_month(result) if count > 0 else previous_month(result)
        return result
    return bucket + timedelta(days=(7 if unit == "week" else 1) * count)


def buckets(start: date, end: date, unit: str) -> list[date]:
    out, current = [], bucket_start(start, unit)
    last = bucket_start(end, unit)
    while current <= last:
        out.append(current)
        current = step(current, unit)
    return out


def months_between(start: date, end: date) -> list[date]:
    return buckets(start, end, "month")


def check_unit(unit: str) -> str:
    if unit not in UNITS:
        raise ValueError(f"granularity must be one of {', '.join(UNITS)}")
    return unit


# ---- data notes -----------------------------------------------------------------------------------


def data_notes(session: Session) -> dict[str, Any]:
    from app.billing.views import last_refreshed

    demo_clients = session.execute(text("SELECT count(*) FROM clients WHERE is_demo")).scalar_one()
    through = session.execute(
        text("SELECT max(occurred_at)::date FROM usage_events WHERE is_demo")
    ).scalar_one()
    refreshed = last_refreshed(session)
    return {
        "includes_demo": bool(demo_clients),
        "demo_through": through.isoformat() if through else None,
        "refreshed_at": refreshed.isoformat() if refreshed else None,
    }


# ---- KPIs -------------------------------------------------------------------------------------------


def monthly_kpis(
    session: Session, f: Filters, start_month: date, end_month: date
) -> list[dict[str, Any]]:
    """One row per month: MRR, ARR, active clients, ARPA, NRR, collections rate, receivables."""
    sql = f"""
    WITH months AS (
        SELECT gs::date AS month
        FROM generate_series(CAST(:from_month AS date), CAST(:to_month AS date), interval '1 month') gs
    ),
    mrr AS (
        SELECT s.month, sum(s.mrr) AS mrr, count(*) FILTER (WHERE s.mrr > 0) AS active
        FROM mv_client_mrr_series s JOIN clients c ON c.id = s.client_id
        WHERE s.month BETWEEN :from_month AND :to_month
          AND {demo("c")} AND {by_client("s.client_id")} AND {by_plan("s.plan_code")}
        GROUP BY s.month
    ),
    nrr AS (
        SELECT cur.month, sum(cur.mrr) AS retained, sum(old.mrr) AS base
        FROM mv_client_mrr_series cur
        JOIN mv_client_mrr_series old
          ON old.client_id = cur.client_id AND old.month = (cur.month - interval '12 months')::date
        JOIN clients c ON c.id = cur.client_id
        WHERE cur.month BETWEEN :from_month AND :to_month AND old.mrr > 0
          AND {demo("c")} AND {by_client("cur.client_id")} AND {by_plan("cur.plan_code")}
        GROUP BY cur.month
    ),
    inv AS (
        SELECT m.month, (m.month + interval '1 month' - interval '1 day')::date AS me,
               i.total, i.issued_on, i.paid_on
        FROM months m
        JOIN invoices i
          ON i.issued_on <= (m.month + interval '1 month' - interval '1 day')::date
         AND i.status IN {REVENUE_STATUSES}
        JOIN clients c ON c.id = i.client_id
        LEFT JOIN subscriptions sb ON sb.id = i.subscription_id
        LEFT JOIN plans p ON p.id = sb.plan_id
        WHERE {demo("c")} AND {by_client("i.client_id")} AND {by_plan("p.code")}
    ),
    bill AS (
        SELECT month,
               sum(total) FILTER (WHERE issued_on > me - interval '12 months') AS billed,
               sum(total) FILTER (WHERE issued_on > me - interval '12 months' AND paid_on <= me) AS paid,
               sum(total) FILTER (WHERE paid_on IS NULL OR paid_on > me) AS receivables
        FROM inv GROUP BY month
    )
    SELECT m.month, mrr.mrr, mrr.active, nrr.retained, nrr.base, bill.billed, bill.paid, bill.receivables
    FROM months m
    LEFT JOIN mrr USING (month) LEFT JOIN nrr USING (month) LEFT JOIN bill USING (month)
    ORDER BY m.month
    """
    out = []
    for r in rows(session, sql, {**f.params(), "from_month": start_month, "to_month": end_month}):
        mrr_value = float(r["mrr"] or 0)
        active = int(r["active"] or 0)
        out.append({
            "month": r["month"],
            "mrr": mrr_value,
            "arr": round(mrr_value * 12, 2),
            "active_clients": active,
            "arpa": round(mrr_value / active, 2) if active else 0.0,
            "nrr": round(100 * float(r["retained"]) / float(r["base"]), 2) if r["base"] else None,
            "collections_rate": round(100 * float(r["paid"] or 0) / float(r["billed"]), 2) if r["billed"] else None,
            "receivables": float(r["receivables"] or 0),
        })  # fmt: skip
    return out


KPI_KEYS = ("mrr", "arr", "nrr", "arpa", "collections_rate", "receivables")


def kpi_summary(session: Session, f: Filters, as_of: date) -> dict[str, Any]:
    """KPI row with the value, the previous period (one month earlier), the delta and a
    12 month sparkline for each of MRR, ARR, NRR, ARPA, collections rate and receivables."""
    current = month_start(as_of)
    series = monthly_kpis(session, f, step(current, "month", -12), current)
    last, before = series[-1], series[-2] if len(series) > 1 else None
    kpis: dict[str, Any] = {}
    for key in KPI_KEYS:
        value, previous = last[key], before[key] if before else None
        delta = None if value is None or previous is None else round(value - previous, 2)
        pct = round(100 * delta / previous, 2) if delta is not None and previous else None
        kpis[key] = {
            "value": value, "previous": previous, "delta": delta, "delta_pct": pct,
            "sparkline": [row[key] for row in series],
        }  # fmt: skip
    return {
        "as_of": as_of,
        "month": current,
        "kpis": kpis,
        "active_clients": last["active_clients"],
    }


# ---- time series --------------------------------------------------------------------------------------

REVENUE_KINDS = {
    "revenue": None, "subscription_revenue": "subscription",
    "addon_revenue": "addon", "overage_revenue": "overage",
}  # fmt: skip
MRR_METRICS = {
    "mrr": "sum(s.mrr)",
    "new_mrr": "sum(s.mrr) FILTER (WHERE s.movement = 'new')",
    "expansion_mrr": "sum(s.mrr - s.prev_mrr) FILTER (WHERE s.movement = 'expansion')",
    "contraction_mrr": "sum(s.prev_mrr - s.mrr) FILTER (WHERE s.movement = 'contraction')",
    "churned_mrr": "sum(s.prev_mrr) FILTER (WHERE s.movement = 'churn')",
    "active_clients": "count(*) FILTER (WHERE s.mrr > 0)",
}
GROWTH_METRICS = ("mrr_growth_rate", "mrr_growth_ma3")
FLOW_METRICS = ("cash_collected", "invoices_issued", "reports_generated")
METRICS = tuple(REVENUE_KINDS) + tuple(MRR_METRICS) + GROWTH_METRICS + FLOW_METRICS
MONTHLY_ONLY = tuple(MRR_METRICS) + GROWTH_METRICS
UNIT_OF = {"cash_collected": "currency", "invoices_issued": "count", "reports_generated": "count",
           "active_clients": "count", "mrr_growth_rate": "percent", "mrr_growth_ma3": "percent"}  # fmt: skip


def _raw_series(
    session: Session, f: Filters, metric: str, unit: str, start: date, end: date
) -> dict[date, float]:
    """Metric values per bucket start between start and end (missing buckets are absent)."""
    params = {**f.params(), "from_day": start, "to_day": end}
    if metric in MRR_METRICS:
        sql = f"""
        SELECT s.month AS bucket, {MRR_METRICS[metric]} AS value
        FROM mv_client_mrr_series s JOIN clients c ON c.id = s.client_id
        WHERE s.month BETWEEN date_trunc('month', CAST(:from_day AS date)) AND CAST(:to_day AS date)
          AND {demo("c")} AND {by_client("s.client_id")} AND {by_plan("s.plan_code")}
        GROUP BY s.month"""
    elif metric in REVENUE_KINDS and unit == "month":
        column = {None: "total", "subscription": "subscription_amount", "addon": "addon_amount",
                  "overage": "overage_amount"}[REVENUE_KINDS[metric]]  # fmt: skip
        sql = f"""
        SELECT r.month AS bucket, sum(r.{column}) AS value
        FROM mv_client_revenue_month r JOIN clients c ON c.id = r.client_id
        WHERE r.month BETWEEN date_trunc('month', CAST(:from_day AS date)) AND CAST(:to_day AS date)
          AND {demo("c")} AND {by_client("r.client_id")} AND {by_plan("r.plan_code")}
        GROUP BY r.month"""
    elif metric in REVENUE_KINDS:  # day and week: recognised on the issue date
        kind = REVENUE_KINDS[metric]
        filter_kind = f"AND l.kind = '{kind}'" if kind else ""
        sql = f"""
        SELECT date_trunc('{unit}', i.issued_on)::date AS bucket, sum(l.amount) AS value
        FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id JOIN clients c ON c.id = i.client_id
        LEFT JOIN subscriptions sb ON sb.id = i.subscription_id LEFT JOIN plans p ON p.id = sb.plan_id
        WHERE i.issued_on BETWEEN :from_day AND :to_day AND i.status IN {REVENUE_STATUSES} {filter_kind}
          AND {demo("c")} AND {by_client("i.client_id")} AND {by_plan("p.code")}
        GROUP BY 1"""
    elif metric in ("cash_collected", "invoices_issued"):
        date_column, expr = (
            ("paid_on", "sum(i.total)") if metric == "cash_collected" else ("issued_on", "count(*)")
        )
        sql = f"""
        SELECT date_trunc('{unit}', i.{date_column})::date AS bucket, {expr} AS value
        FROM invoices i JOIN clients c ON c.id = i.client_id
        LEFT JOIN subscriptions sb ON sb.id = i.subscription_id LEFT JOIN plans p ON p.id = sb.plan_id
        WHERE i.{date_column} BETWEEN :from_day AND :to_day AND i.status IN {REVENUE_STATUSES}
          AND {demo("c")} AND {by_client("i.client_id")} AND {by_plan("p.code")}
        GROUP BY 1"""
    elif metric == "reports_generated":
        sql = f"""
        SELECT date_trunc('{unit}', e.occurred_at)::date AS bucket, sum(e.units) AS value
        FROM usage_events e JOIN clients c ON c.id = e.client_id LEFT JOIN plans p ON p.id = e.plan_id
        WHERE e.event_type = 'report_generated' AND e.occurred_at >= :from_day AND e.occurred_at < CAST(:to_day AS date) + 1
          AND {demo("c")} AND {by_client("e.client_id")} AND {by_plan("p.code")}
        GROUP BY 1"""
    else:
        raise ValueError(f"unknown metric {metric}")
    return {r["bucket"]: float(r["value"] or 0) for r in rows(session, sql, params)}


def _growth(
    session: Session, f: Filters, metric: str, wanted: list[date]
) -> dict[date, float | None]:
    """Month over month MRR growth in percent, or its trailing 3 month average."""
    first = step(wanted[0], "month", -3)
    mrr = _raw_series(session, f, "mrr", "month", first, bucket_end(wanted[-1], "month"))
    growth: dict[date, float | None] = {}
    for month in months_between(first, wanted[-1]):
        before = mrr.get(step(month, "month", -1))
        growth[month] = round(100 * (mrr.get(month, 0.0) - before) / before, 2) if before else None
    if metric == "mrr_growth_rate":
        return {m: growth.get(m) for m in wanted}
    out: dict[date, float | None] = {}
    for month in wanted:
        recent = [growth.get(step(month, "month", -k)) for k in range(3)]
        usable = [g for g in recent if g is not None]
        out[month] = round(sum(usable) / len(usable), 2) if usable else None
    return out


def timeseries(
    session: Session,
    f: Filters,
    metric: str,
    unit: str,
    start: date,
    end: date,
    compare: bool = False,
) -> dict[str, Any]:
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {', '.join(METRICS)}")
    unit = check_unit(unit)
    if metric in MONTHLY_ONLY and unit != "month":
        raise ValueError(f"{metric} is only available with granularity=month")
    if end < start:
        raise ValueError("'to' must not be before 'from'")
    current = buckets(start, end, unit)

    def values(wanted: list[date]) -> dict[date, float | None]:
        if metric in GROWTH_METRICS:
            return _growth(session, f, metric, wanted)
        raw = _raw_series(session, f, metric, unit, wanted[0], bucket_end(wanted[-1], unit))
        return {b: raw.get(b, 0.0) for b in wanted}

    now = values(current)
    previous_buckets = [step(b, unit, -len(current)) for b in current]
    before = values(previous_buckets) if compare else {}
    result = []
    for index, bucket in enumerate(current):
        row: dict[str, Any] = {"period": bucket, "value": now[bucket]}
        if compare:
            row["previous_period"] = previous_buckets[index]
            row["previous"] = before[previous_buckets[index]]
        result.append(row)
    basis = "period month" if unit == "month" else "invoice issue date"
    if metric in MRR_METRICS or metric in GROWTH_METRICS:
        basis = "active subscriptions at month end"
    return {
        "meta": {
            "metric": metric,
            "granularity": unit,
            "from": current[0],
            "to": bucket_end(current[-1], unit),
            "compare": compare,
            "unit": UNIT_OF.get(metric, "currency"),
            "basis": basis,
        },  # fmt: skip
        "rows": result,
    }


# ---- breakdowns, walk, aging, cohorts, margin ---------------------------------------------------------------

DIMENSIONS = {
    "plan": ("r.plan_code", "COALESCE(p.name, r.plan_code)"),
    "client": ("r.client_id::text", "c.name"),
    "industry": ("c.industry", "c.industry"),
    "region": ("c.region", "c.region"),
    "segment": ("COALESCE(c.segment, 'unspecified')", "COALESCE(c.segment, 'unspecified')"),
}


def breakdown(
    session: Session, f: Filters, by: str, start: date, end: date, limit: int | None = None
) -> dict[str, Any]:
    if by not in DIMENSIONS:
        raise ValueError(f"by must be one of {', '.join(DIMENSIONS)}")
    key_sql, label_sql = DIMENSIONS[by]
    params = {**f.params(), "from_month": month_start(start), "to_month": month_start(end),
              "to_end": next_month(month_start(end)), "limit": limit}  # fmt: skip
    sql = f"""
    SELECT {key_sql} AS key, {label_sql} AS label,
           sum(r.total) AS revenue,
           sum(r.subscription_amount) AS subscription,
           sum(r.addon_amount) AS addon,
           sum(r.overage_amount) AS overage,
           count(DISTINCT r.client_id) AS clients,
           100 * sum(r.total) / NULLIF(sum(sum(r.total)) OVER (), 0) AS share_pct,
           sum(r.total) FILTER (WHERE r.month > (CAST(:to_month AS date) - interval '3 months')) AS last3,
           sum(r.total) FILTER (WHERE r.month <= (CAST(:to_month AS date) - interval '3 months')
                                  AND r.month > (CAST(:to_month AS date) - interval '6 months')) AS prior3
    FROM mv_client_revenue_month r
    JOIN clients c ON c.id = r.client_id
    LEFT JOIN plans p ON p.code = r.plan_code
    WHERE r.month BETWEEN :from_month AND :to_month
      AND {demo("c")} AND {by_client("r.client_id")} AND {by_plan("r.plan_code")}
    GROUP BY {key_sql}, {label_sql}
    ORDER BY revenue DESC, label
    LIMIT :limit
    """
    result = rows(session, sql, params)
    usage: dict[str, float] = {}
    if by == "client":
        usage_rows = rows(
            session,
            """SELECT e.client_id::text AS key, sum(e.units) AS reports FROM usage_events e
               WHERE e.event_type = 'report_generated' AND e.occurred_at >= :from_month
                 AND e.occurred_at < :to_end GROUP BY e.client_id""",
            params,
        )
        usage = {u["key"]: u["reports"] for u in usage_rows}
    out = []
    for r in result:
        last3, prior3 = r.pop("last3") or 0.0, r.pop("prior3") or 0.0
        entry = {**r, "share_pct": round(r["share_pct"] or 0.0, 2)}
        if by == "client":
            entry["reports"] = usage.get(r["key"], 0.0)
            entry["trend_pct"] = round(100 * (last3 - prior3) / prior3, 2) if prior3 else None
        out.append(entry)
    total = sum(r["revenue"] or 0.0 for r in out)
    return {"meta": {"by": by, "from": month_start(start), "to": month_start(end), "total": round(total, 2)},
            "rows": out}  # fmt: skip


def mrr_walk(session: Session, f: Filters, start: date, end: date) -> dict[str, Any]:
    """Opening + new + expansion - contraction - churn = closing, for every month."""
    params = {**f.params(), "from_month": month_start(start), "to_month": month_start(end)}
    sql = f"""
    SELECT s.month,
           COALESCE(sum(s.prev_mrr), 0) AS opening,
           COALESCE(sum(s.mrr) FILTER (WHERE s.movement = 'new'), 0) AS new,
           COALESCE(sum(s.mrr - s.prev_mrr) FILTER (WHERE s.movement = 'expansion'), 0) AS expansion,
           COALESCE(sum(s.prev_mrr - s.mrr) FILTER (WHERE s.movement = 'contraction'), 0) AS contraction,
           COALESCE(sum(s.prev_mrr) FILTER (WHERE s.movement = 'churn'), 0) AS churn,
           COALESCE(sum(s.mrr), 0) AS closing,
           count(*) FILTER (WHERE s.movement = 'new') AS new_clients,
           count(*) FILTER (WHERE s.movement = 'churn') AS churned_clients,
           count(*) FILTER (WHERE s.mrr > 0) AS active_clients
    FROM mv_client_mrr_series s JOIN clients c ON c.id = s.client_id
    WHERE s.month BETWEEN :from_month AND :to_month
      AND {demo("c")} AND {by_client("s.client_id")} AND {by_plan("s.plan_code")}
    GROUP BY s.month ORDER BY s.month
    """
    found = {r["month"]: r for r in rows(session, sql, params)}
    empty = {k: 0.0 for k in ("opening", "new", "expansion", "contraction", "churn", "closing")}
    empty.update(new_clients=0, churned_clients=0, active_clients=0)
    out = [{"month": m, **{**empty, **found.get(m, {})}} for m in months_between(start, end)]
    return {"meta": {"from": out[0]["month"], "to": out[-1]["month"]}, "rows": out}


AGING_BUCKETS = ("current", "1-30", "31-60", "60+")


def aging(session: Session, f: Filters, as_of: date) -> dict[str, Any]:
    """Unpaid issued invoices by days past due, plus the invoice status table."""
    params = {**f.params(), "as_of": as_of}
    base = f"""
        FROM invoices i JOIN clients c ON c.id = i.client_id
        LEFT JOIN subscriptions sb ON sb.id = i.subscription_id LEFT JOIN plans p ON p.id = sb.plan_id
        WHERE {demo("c")} AND {by_client("i.client_id")} AND {by_plan("p.code")}"""
    buckets_sql = f"""
    SELECT bucket, count(*) AS invoices, sum(total) AS amount FROM (
        SELECT i.total, CASE WHEN CAST(:as_of AS date) <= i.due_on THEN 'current'
                             WHEN CAST(:as_of AS date) - i.due_on <= 30 THEN '1-30'
                             WHEN CAST(:as_of AS date) - i.due_on <= 60 THEN '31-60'
                             ELSE '60+' END AS bucket
        {base} AND i.issued_on <= :as_of AND i.status IN {REVENUE_STATUSES}
          AND (i.paid_on IS NULL OR i.paid_on > :as_of)
    ) t GROUP BY bucket"""
    found = {r["bucket"]: r for r in rows(session, buckets_sql, params)}
    table = [{"bucket": b, "invoices": int(found.get(b, {}).get("invoices", 0)),
              "amount": float(found.get(b, {}).get("amount", 0.0))} for b in AGING_BUCKETS]  # fmt: skip
    statuses = rows(
        session,
        f"SELECT i.status AS status, count(*) AS invoices, sum(i.total) AS amount {base} GROUP BY i.status ORDER BY i.status",
        params,
    )
    return {
        "meta": {"as_of": as_of, "outstanding": round(sum(r["amount"] for r in table), 2)},
        "rows": table,
        "statuses": statuses,
    }


def cohorts(session: Session, f: Filters) -> dict[str, Any]:
    """Signup-month cohorts: the share of clients still paying k months after signing up."""
    sql = f"""
    WITH cohort AS (
        SELECT c.id, date_trunc('month', c.signed_up_on)::date AS cohort
        FROM clients c WHERE {demo("c")} AND {by_client("c.id")}
    ),
    size AS (SELECT cohort, count(*) AS n FROM cohort GROUP BY cohort),
    active AS (
        SELECT co.cohort,
               (extract(year FROM age(s.month, co.cohort)) * 12 + extract(month FROM age(s.month, co.cohort)))::int AS k,
               count(*) AS retained
        FROM cohort co JOIN mv_client_mrr_series s ON s.client_id = co.id AND s.mrr > 0
        WHERE s.month >= co.cohort
        GROUP BY co.cohort, k
    )
    SELECT size.cohort, size.n AS size, active.k AS months_since, COALESCE(active.retained, 0) AS retained
    FROM size LEFT JOIN active ON active.cohort = size.cohort
    ORDER BY size.cohort, active.k
    """
    found = rows(session, sql, f.params())
    latest = max((r["cohort"] for r in found), default=None)
    long_rows, matrix = [], {}
    for r in found:
        if r["months_since"] is None:
            continue
        rate = round(100 * r["retained"] / r["size"], 1)
        long_rows.append({"cohort": r["cohort"], "size": int(r["size"]), "months_since": int(r["months_since"]),
                          "retained": int(r["retained"]), "retention_pct": rate})  # fmt: skip
        matrix.setdefault(
            r["cohort"], {"cohort": r["cohort"], "size": int(r["size"]), "retention": {}}
        )
        matrix[r["cohort"]]["retention"][int(r["months_since"])] = rate
    return {"meta": {"latest_cohort": latest}, "rows": long_rows, "matrix": list(matrix.values())}


def margin(
    session: Session, settings: Settings, f: Filters, start: date, end: date
) -> dict[str, Any]:
    """Revenue minus modelled token cost and infrastructure cost, per month."""
    params = {**f.params(), **price_params(settings), "from_month": month_start(start),
              "to_month": month_start(end), "to_end": next_month(month_start(end))}  # fmt: skip
    revenue = {r["month"]: r["revenue"] for r in rows(
        session,
        f"""SELECT r.month, sum(r.total) AS revenue FROM mv_client_revenue_month r JOIN clients c ON c.id = r.client_id
            WHERE r.month BETWEEN :from_month AND :to_month AND {demo('c')} AND {by_client('r.client_id')}
              AND {by_plan('r.plan_code')} GROUP BY r.month""",
        params,
    )}  # fmt: skip
    cost = {r["month"]: r["cost"] for r in rows(
        session,
        f"""SELECT date_trunc('month', l.created_at)::date AS month, sum({TOKEN_COST_SQL}) AS cost
            FROM llm_calls l LEFT JOIN cases ca ON ca.id = l.case_id
            WHERE l.created_at >= :from_month AND l.created_at < :to_end AND NOT l.cache_hit
              AND l.status IN {LLM_OK} AND (:include_demo OR NOT COALESCE(ca.is_demo, false))
              AND {by_client('ca.client_id')}
            GROUP BY 1""",
        params,
    )}  # fmt: skip
    out = []
    for month in months_between(start, end):
        income, tokens = revenue.get(month, 0.0) or 0.0, cost.get(month, 0.0) or 0.0
        profit = income - tokens - settings.infra_cost_monthly
        out.append({"month": month, "revenue": round(income, 2), "token_cost": round(tokens, 2),
                    "infra_cost": settings.infra_cost_monthly, "gross_margin": round(profit, 2),
                    "gross_margin_pct": round(100 * profit / income, 1) if income else None})  # fmt: skip
    return {"meta": {"basis": "modelled at reference prices, see PRICE_* settings",
                     "infra_cost_monthly": settings.infra_cost_monthly}, "rows": out}  # fmt: skip


# ---- operations ---------------------------------------------------------------------------------------------


def _case_filters(f: Filters) -> str:
    return f"(:include_demo OR NOT ca.is_demo) AND {by_client('ca.client_id')}"


def ops_timeseries(
    session: Session, f: Filters, metric: str, unit: str, start: date, end: date
) -> dict[str, Any]:
    unit = check_unit(unit)
    sources = {
        "cases_created": ("cases ca", "ca.created_at", "count(*)", ""),
        "cases_approved": (
            "review_events re JOIN cases ca ON ca.id = re.case_id",
            "re.created_at",
            "count(*)",
            "AND re.event_type = 'approved'",
        ),
    }
    if metric not in sources:
        raise ValueError(f"metric must be one of {', '.join(sources)}")
    table, column, expr, extra = sources[metric]
    sql = f"""
    SELECT date_trunc('{unit}', {column})::date AS bucket, {expr} AS value
    FROM {table}
    WHERE {column} >= :from_day AND {column} < CAST(:to_day AS date) + 1 {extra} AND {_case_filters(f)}
    GROUP BY 1"""
    found = {
        r["bucket"]: r["value"]
        for r in rows(session, sql, {**f.params(), "from_day": start, "to_day": end})
    }
    series = [{"period": b, "value": float(found.get(b, 0))} for b in buckets(start, end, unit)]
    return {"meta": {"metric": metric, "granularity": unit, "from": series[0]["period"], "unit": "count"},
            "rows": series}  # fmt: skip


def funnel(session: Session, f: Filters, start: date, end: date) -> dict[str, Any]:
    sql = f"""
    SELECT count(*) AS intake,
           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM search_runs sr WHERE sr.case_id = ca.id)) AS searched,
           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM claim_charts ch WHERE ch.case_id = ca.id)
                              OR EXISTS (SELECT 1 FROM review_events x WHERE x.case_id = ca.id
                                         AND x.event_type IN ('submitted', 'approved'))) AS charted,
           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM review_events x WHERE x.case_id = ca.id
                                          AND x.event_type IN ('submitted', 'approved'))) AS reviewed,
           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM review_events x WHERE x.case_id = ca.id
                                          AND x.event_type = 'approved')) AS approved
    FROM cases ca
    WHERE ca.created_at >= :from_day AND ca.created_at < CAST(:to_day AS date) + 1 AND {_case_filters(f)}
    """
    row = rows(session, sql, {**f.params(), "from_day": start, "to_day": end})[0]
    stages = ("intake", "searched", "charted", "reviewed", "approved")
    return {"meta": {"from": start, "to": end},
            "rows": [{"stage": s, "cases": int(row[s] or 0)} for s in stages]}  # fmt: skip


def risk_distribution(session: Session, f: Filters, start: date, end: date) -> dict[str, Any]:
    sql = f"""
    SELECT date_trunc('month', ca.created_at)::date AS month, ca.risk_level AS level, count(*) AS cases
    FROM cases ca
    WHERE ca.risk_level IS NOT NULL AND ca.created_at >= :from_day AND ca.created_at < CAST(:to_day AS date) + 1
      AND {_case_filters(f)}
    GROUP BY 1, 2 ORDER BY 1, 2"""
    found = {
        (r["month"], r["level"]): int(r["cases"])
        for r in rows(session, sql, {**f.params(), "from_day": start, "to_day": end})
    }
    levels = ("low", "medium", "medium_high", "high")
    out = [
        {"month": m, **{lvl: found.get((m, lvl), 0) for lvl in levels}}
        for m in months_between(start, end)
    ]
    return {"meta": {"levels": list(levels)}, "rows": out}


def cpc_areas(
    session: Session, f: Filters, start: date, end: date, limit: int = 15
) -> dict[str, Any]:
    """Technology areas searched: the CPC subclasses suggested by search runs, weighted by votes."""
    params = {**f.params(), "from_day": start, "to_day": end, "limit": limit}
    base = f"""
        FROM search_runs sr JOIN cases ca ON ca.id = sr.case_id,
             jsonb_array_elements(sr.suggested_cpc) AS item
        WHERE sr.created_at >= :from_day AND sr.created_at < CAST(:to_day AS date) + 1 AND {_case_filters(f)}"""
    top = rows(
        session,
        f"SELECT item->>'subclass' AS subclass, sum((item->>'votes')::int) AS votes, count(*) AS searches {base} "
        "GROUP BY 1 ORDER BY votes DESC, subclass LIMIT :limit",
        params,
    )
    heat = rows(
        session,
        f"""WITH top AS (SELECT item->>'subclass' AS subclass {base} GROUP BY 1
                         ORDER BY sum((item->>'votes')::int) DESC LIMIT :limit)
            SELECT date_trunc('month', sr.created_at)::date AS month, item->>'subclass' AS subclass,
                   sum((item->>'votes')::int) AS votes
            FROM search_runs sr JOIN cases ca ON ca.id = sr.case_id, jsonb_array_elements(sr.suggested_cpc) AS item
            WHERE sr.created_at >= :from_day AND sr.created_at < CAST(:to_day AS date) + 1 AND {_case_filters(f)}
              AND item->>'subclass' IN (SELECT subclass FROM top)
            GROUP BY 1, 2 ORDER BY 1, 2""",
        params,
    )
    return {"meta": {"from": start, "to": end}, "rows": top, "heatmap": heat}


HOURS_EDGES = (4, 8, 24, 48, 72, 168)


def turnaround(session: Session, f: Filters, start: date, end: date) -> dict[str, Any]:
    """Hours from intake (case created) to approval, as summary, histogram and monthly trend."""
    base = f"""
        WITH t AS (
            SELECT ca.id, ca.created_at, min(re.created_at) AS approved_at
            FROM cases ca JOIN review_events re ON re.case_id = ca.id AND re.event_type = 'approved'
            WHERE ca.created_at >= :from_day AND ca.created_at < CAST(:to_day AS date) + 1 AND {_case_filters(f)}
            GROUP BY ca.id, ca.created_at
        ),
        h AS (SELECT id, date_trunc('month', approved_at)::date AS month,
                     extract(epoch FROM approved_at - created_at) / 3600.0 AS hours FROM t)"""
    params = {**f.params(), "from_day": start, "to_day": end}
    summary = rows(
        session,
        base
        + """SELECT count(*) AS cases, avg(hours) AS mean_hours,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY hours) AS p50_hours,
                  percentile_cont(0.9) WITHIN GROUP (ORDER BY hours) AS p90_hours FROM h""",
        params,
    )[0]
    edges = ",".join(f"{e}" for e in HOURS_EDGES)
    histogram = rows(
        session,
        base
        + f"""SELECT width_bucket(hours, ARRAY[{edges}]::float8[]) AS bin, count(*) AS cases FROM h GROUP BY 1 ORDER BY 1""",
        params,
    )
    labels = (
        [f"0-{HOURS_EDGES[0]}h"]
        + [f"{a}-{b}h" for a, b in zip(HOURS_EDGES, HOURS_EDGES[1:], strict=False)]
        + [f"{HOURS_EDGES[-1]}h+"]
    )
    counts = {int(r["bin"]): int(r["cases"]) for r in histogram}
    trend = rows(
        session,
        base
        + """SELECT month, count(*) AS cases,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY hours) AS p50_hours,
                  percentile_cont(0.9) WITHIN GROUP (ORDER BY hours) AS p90_hours FROM h GROUP BY month ORDER BY month""",
        params,
    )
    return {
        "meta": {"from": start, "to": end, "unit": "hours"},
        "summary": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in summary.items()},
        "rows": [{"bucket": labels[i], "cases": counts.get(i, 0)} for i in range(len(labels))],
        "trend": [
            {**t, "p50_hours": round(t["p50_hours"], 2), "p90_hours": round(t["p90_hours"], 2)}
            for t in trend
        ],
    }


def attorneys(session: Session, f: Filters, start: date, end: date) -> dict[str, Any]:
    sql = f"""
    SELECT u.id::text AS user_id, u.full_name AS name, r.name AS role, u.is_demo,
           count(*) AS cases,
           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM review_events x WHERE x.case_id = ca.id AND x.event_type = 'approved')) AS approved,
           count(*) FILTER (WHERE ca.status IN ('in_review', 'changes_requested')) AS in_review
    FROM cases ca JOIN users u ON u.id = ca.owner_id JOIN roles r ON r.id = u.role_id
    WHERE ca.created_at >= :from_day AND ca.created_at < CAST(:to_day AS date) + 1 AND {_case_filters(f)}
    GROUP BY u.id, u.full_name, r.name, u.is_demo
    ORDER BY cases DESC, name LIMIT 100"""
    return {"meta": {"from": start, "to": end},
            "rows": rows(session, sql, {**f.params(), "from_day": start, "to_day": end})}  # fmt: skip


def latency(session: Session, f: Filters, start: date, end: date) -> dict[str, Any]:
    sql = f"""
    SELECT date_trunc('month', sr.created_at)::date AS month, count(*) AS searches,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY (sr.timings_ms->>'total')::float8) AS p50_ms,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY (sr.timings_ms->>'total')::float8) AS p95_ms
    FROM search_runs sr JOIN cases ca ON ca.id = sr.case_id
    WHERE sr.created_at >= :from_day AND sr.created_at < CAST(:to_day AS date) + 1
      AND jsonb_exists(sr.timings_ms, 'total') AND {_case_filters(f)}
    GROUP BY 1 ORDER BY 1"""
    found = {
        r["month"]: r for r in rows(session, sql, {**f.params(), "from_day": start, "to_day": end})
    }
    out = [{"month": m, "searches": int(found[m]["searches"]) if m in found else 0,
            "p50_ms": round(found[m]["p50_ms"], 1) if m in found else None,
            "p95_ms": round(found[m]["p95_ms"], 1) if m in found else None} for m in months_between(start, end)]  # fmt: skip
    return {"meta": {"unit": "ms"}, "rows": out}


def backlog(session: Session, f: Filters) -> dict[str, Any]:
    sql = f"""
    SELECT CASE WHEN now() - ca.updated_at < interval '1 day' THEN 'under 1 day'
                WHEN now() - ca.updated_at < interval '3 days' THEN '1-3 days'
                WHEN now() - ca.updated_at < interval '7 days' THEN '3-7 days'
                ELSE 'over 7 days' END AS age, ca.status, count(*) AS cases
    FROM cases ca WHERE ca.status IN ('in_review', 'changes_requested') AND {_case_filters(f)}
    GROUP BY 1, 2 ORDER BY 1, 2"""
    found = rows(session, sql, f.params())
    return {"meta": {"total": sum(int(r["cases"]) for r in found)}, "rows": found}


# ---- LLM efficiency ------------------------------------------------------------------------------------------


def _llm_filters(f: Filters) -> str:
    return f"(:include_demo OR NOT COALESCE(ca.is_demo, false)) AND {by_client('ca.client_id')}"


def llm_tokens(session: Session, f: Filters, unit: str, start: date, end: date) -> dict[str, Any]:
    unit = check_unit(unit)
    sql = f"""
    SELECT date_trunc('{unit}', l.created_at)::date AS bucket, l.provider, sum(l.tokens_in) AS tokens_in,
           sum(l.tokens_out) AS tokens_out, count(*) AS calls
    FROM llm_calls l LEFT JOIN cases ca ON ca.id = l.case_id
    WHERE l.created_at >= :from_day AND l.created_at < CAST(:to_day AS date) + 1
      AND NOT l.cache_hit AND l.status IN {LLM_OK} AND {_llm_filters(f)}
    GROUP BY 1, 2 ORDER BY 1, 2"""
    found = {
        (r["bucket"], r["provider"]): r
        for r in rows(session, sql, {**f.params(), "from_day": start, "to_day": end})
    }
    out = []
    for bucket in buckets(start, end, unit):
        for provider in ("groq", "gemini"):
            r = found.get((bucket, provider))
            out.append({"period": bucket, "provider": provider,
                        "tokens_in": int(r["tokens_in"]) if r else 0, "tokens_out": int(r["tokens_out"]) if r else 0,
                        "tokens": int(r["tokens_in"] + r["tokens_out"]) if r else 0, "calls": int(r["calls"]) if r else 0})  # fmt: skip
    return {"meta": {"granularity": unit}, "rows": out}


def llm_efficiency(
    session: Session, settings: Settings, f: Filters, start: date, end: date
) -> dict[str, Any]:
    """Monthly cache hit rate, fallback rate and tokens per case, with the target line."""
    sql = f"""
    SELECT date_trunc('month', l.created_at)::date AS month,
           count(*) FILTER (WHERE l.cache_hit) AS cache_calls,
           count(*) FILTER (WHERE NOT l.cache_hit AND l.status IN {LLM_OK}) AS provider_calls,
           count(*) FILTER (WHERE NOT l.cache_hit AND l.status IN {LLM_OK} AND l.provider = 'gemini') AS fallback_calls,
           COALESCE(sum(l.tokens_in + l.tokens_out) FILTER (WHERE NOT l.cache_hit AND l.status IN {LLM_OK}), 0) AS tokens,
           count(DISTINCT l.case_id) FILTER (WHERE NOT l.cache_hit AND l.status IN {LLM_OK}) AS cases
    FROM llm_calls l LEFT JOIN cases ca ON ca.id = l.case_id
    WHERE l.created_at >= :from_month AND l.created_at < :to_end AND {_llm_filters(f)}
    GROUP BY 1 ORDER BY 1"""
    params = {
        **f.params(),
        "from_month": month_start(start),
        "to_end": next_month(month_start(end)),
    }
    found = {r["month"]: r for r in rows(session, sql, params)}
    out = []
    for month in months_between(start, end):
        r = found.get(month)
        total = (r["cache_calls"] + r["provider_calls"]) if r else 0
        out.append({
            "month": month,
            "calls": int(total),
            "cache_hit_rate": round(100 * r["cache_calls"] / total, 1) if r and total else None,
            "fallback_rate": round(100 * r["fallback_calls"] / r["provider_calls"], 1) if r and r["provider_calls"] else None,
            "tokens": int(r["tokens"]) if r else 0,
            "cases": int(r["cases"]) if r else 0,
            "tokens_per_case": round(r["tokens"] / r["cases"]) if r and r["cases"] else None,
            "target": settings.token_target_per_case,
        })  # fmt: skip
    return {"meta": {"target_tokens_per_case": settings.token_target_per_case}, "rows": out}


def llm_cost(
    session: Session, settings: Settings, f: Filters, start: date, end: date
) -> dict[str, Any]:
    """Modelled LLM cost per case next to the revenue per case, per month."""
    params = {**f.params(), **price_params(settings), "from_month": month_start(start),
              "to_end": next_month(month_start(end)), "to_month": month_start(end)}  # fmt: skip
    cost = {r["month"]: r for r in rows(
        session,
        f"""SELECT date_trunc('month', l.created_at)::date AS month, sum({TOKEN_COST_SQL}) AS cost,
                   count(DISTINCT l.case_id) AS cases
            FROM llm_calls l LEFT JOIN cases ca ON ca.id = l.case_id
            WHERE l.created_at >= :from_month AND l.created_at < :to_end AND NOT l.cache_hit
              AND l.status IN {LLM_OK} AND {_llm_filters(f)} GROUP BY 1""",
        params,
    )}  # fmt: skip
    revenue = {r["month"]: r["revenue"] for r in rows(
        session,
        f"""SELECT r.month, sum(r.total) AS revenue FROM mv_client_revenue_month r JOIN clients c ON c.id = r.client_id
            WHERE r.month BETWEEN :from_month AND :to_month AND {demo('c')} AND {by_client('r.client_id')}
              AND {by_plan('r.plan_code')} GROUP BY r.month""",
        params,
    )}  # fmt: skip
    reports = {r["month"]: r["reports"] for r in rows(
        session,
        f"""SELECT date_trunc('month', e.occurred_at)::date AS month, sum(e.units) AS reports
            FROM usage_events e JOIN clients c ON c.id = e.client_id
            WHERE e.event_type = 'report_generated' AND e.occurred_at >= :from_month AND e.occurred_at < :to_end
              AND {demo('c')} AND {by_client('e.client_id')} GROUP BY 1""",
        params,
    )}  # fmt: skip
    out = []
    for month in months_between(start, end):
        c = cost.get(month)
        cases = int(c["cases"]) if c else 0
        spend = c["cost"] or 0.0 if c else 0.0
        income, made = revenue.get(month) or 0.0, reports.get(month) or 0.0
        per_case = round(spend / cases, 4) if cases else None
        revenue_per = round(income / made, 2) if made else None
        out.append({"month": month, "cost": round(spend, 2), "cases": cases, "cost_per_case": per_case,
                    "revenue": round(income, 2), "reports": int(made), "revenue_per_case": revenue_per,
                    "margin_per_case": round(revenue_per - per_case, 2) if per_case is not None and revenue_per is not None else None})  # fmt: skip
    return {"meta": {"basis": "modelled at reference prices, see PRICE_* settings"}, "rows": out}
