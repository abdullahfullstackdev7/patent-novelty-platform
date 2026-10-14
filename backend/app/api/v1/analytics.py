"""Analytics API (admin only): revenue, operations and LLM efficiency, with CSV export.

Every endpoint takes the shared filter bar (from, to, include_demo, client_id, plan) and
`format=csv` to download the rows. Numbers come from app.billing.queries.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.deps import SessionDep, SettingsDep, require
from app.billing import queries
from app.billing.queries import Filters
from app.billing.subscriptions import month_start
from app.security import policy

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(require(policy.can_view_analytics))],
)

CSV_UNSAFE_START = ("=", "+", "-", "@", "\t", "\r")


def to_csv(rows: list[dict[str, Any]]) -> str:
    """CSV text. Strings that a spreadsheet would run as a formula get a leading quote."""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, str) and value.startswith(CSV_UNSAFE_START):
                value = "'" + value
            values.append("" if value is None else value)
        writer.writerow(values)
    return out.getvalue()


def filters(
    include_demo: bool = Query(default=True, description="Include seeded demo data"),
    client_id: uuid.UUID | None = None,
    plan: str | None = Query(default=None, max_length=32, pattern="^[a-z0-9_-]+$"),
) -> Filters:
    return Filters(include_demo, client_id, plan)


FilterDep = Depends(filters)


class Range:
    def __init__(self, start: date, end: date) -> None:
        self.start, self.end = start, end


def date_range(
    from_: date | None = Query(default=None, alias="from"), to: date | None = None
) -> Range:
    """Default: the current month and the 11 before it."""
    end = to or date.today()
    start = from_ or queries.step(month_start(end), "month", -11)
    if end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "'to' must not be before 'from'")
    if (end - start).days > 366 * 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The range is limited to 5 years")
    return Range(start, end)


RangeDep = Depends(date_range)
Format = Query(default="json", pattern="^(json|csv)$")


def respond(session, payload: dict[str, Any], fmt: str, name: str):
    payload["meta"] = {**payload.get("meta", {}), **queries.data_notes(session)}
    if fmt == "csv":
        return Response(
            to_csv(payload["rows"]), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )  # fmt: skip
    return payload


def guard(call):
    """Turn the query layer's ValueError (bad metric, granularity) into a 422."""
    try:
        return call()
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from None


# ---- revenue ---------------------------------------------------------------------------------------------


@router.get("/revenue/summary")
def revenue_summary(
    session: SessionDep, f: Filters = FilterDep, as_of: date | None = None, format: str = Format
):
    """KPIs with the previous month, the delta and a 12 month sparkline."""
    data = queries.kpi_summary(session, f, as_of or date.today())
    flat = [
        {"kpi": k, **{x: v for x, v in row.items() if x != "sparkline"}}
        for k, row in data["kpis"].items()
    ]
    return respond(session, {"meta": {"as_of": data["as_of"], "month": data["month"], "active_clients": data["active_clients"]},
                             "kpis": data["kpis"], "rows": flat}, format, "revenue-summary")  # fmt: skip


@router.get("/revenue/timeseries")
def revenue_timeseries(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep,
    metric: str = Query(default="revenue", max_length=32),
    granularity: str = Query(default="month", max_length=8),
    compare: str | None = Query(default=None, pattern="^previous$"),
    format: str = Format,
):  # fmt: skip
    data = guard(
        lambda: queries.timeseries(
            session, f, metric, granularity, r.start, r.end, compare == "previous"
        )
    )
    return respond(session, data, format, f"revenue-{metric}-{granularity}")


@router.get("/revenue/breakdown")
def revenue_breakdown(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep,
    by: str = Query(default="plan", max_length=16), limit: int | None = Query(default=None, ge=1, le=200),
    format: str = Format,
):  # fmt: skip
    data = guard(lambda: queries.breakdown(session, f, by, r.start, r.end, limit))
    return respond(session, data, format, f"revenue-by-{by}")


@router.get("/revenue/mrr-walk")
def revenue_mrr_walk(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep, format: str = Format
):
    """Opening MRR, new, expansion, contraction, churn and closing MRR per month (the waterfall)."""
    return respond(session, queries.mrr_walk(session, f, r.start, r.end), format, "mrr-walk")


@router.get("/revenue/aging")
def revenue_aging(
    session: SessionDep, f: Filters = FilterDep, as_of: date | None = None, format: str = Format
):
    return respond(
        session, queries.aging(session, f, as_of or date.today()), format, "invoice-aging"
    )


@router.get("/revenue/cohorts")
def revenue_cohorts(session: SessionDep, f: Filters = FilterDep, format: str = Format):
    """Signup-month cohorts and how many clients still pay k months later."""
    return respond(session, queries.cohorts(session, f), format, "cohort-retention")


@router.get("/revenue/margin")
def revenue_margin(
    session: SessionDep,
    settings: SettingsDep,
    f: Filters = FilterDep,
    r: Range = RangeDep,
    format: str = Format,
):
    return respond(
        session, queries.margin(session, settings, f, r.start, r.end), format, "gross-margin"
    )


# ---- operations -----------------------------------------------------------------------------------------------


@router.get("/ops/timeseries")
def ops_timeseries(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep,
    metric: str = Query(default="cases_created", max_length=24),
    granularity: str = Query(default="day", max_length=8), format: str = Format,
):  # fmt: skip
    data = guard(lambda: queries.ops_timeseries(session, f, metric, granularity, r.start, r.end))
    return respond(session, data, format, f"ops-{metric}")


@router.get("/ops/funnel")
def ops_funnel(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep, format: str = Format
):
    return respond(session, queries.funnel(session, f, r.start, r.end), format, "case-funnel")


@router.get("/ops/risk")
def ops_risk(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep, format: str = Format
):
    return respond(
        session, queries.risk_distribution(session, f, r.start, r.end), format, "risk-distribution"
    )


@router.get("/ops/cpc")
def ops_cpc(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep,
    limit: int = Query(default=15, ge=1, le=50), format: str = Format,
):  # fmt: skip
    return respond(
        session, queries.cpc_areas(session, f, r.start, r.end, limit), format, "technology-areas"
    )


@router.get("/ops/turnaround")
def ops_turnaround(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep, format: str = Format
):
    return respond(session, queries.turnaround(session, f, r.start, r.end), format, "turnaround")


@router.get("/ops/attorneys")
def ops_attorneys(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep, format: str = Format
):
    return respond(
        session, queries.attorneys(session, f, r.start, r.end), format, "attorney-throughput"
    )


@router.get("/ops/latency")
def ops_latency(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep, format: str = Format
):
    return respond(session, queries.latency(session, f, r.start, r.end), format, "search-latency")


@router.get("/ops/backlog")
def ops_backlog(session: SessionDep, f: Filters = FilterDep, format: str = Format):
    return respond(session, queries.backlog(session, f), format, "review-backlog")


# ---- LLM ----------------------------------------------------------------------------------------------------------


@router.get("/llm/tokens")
def llm_tokens(
    session: SessionDep, f: Filters = FilterDep, r: Range = RangeDep,
    granularity: str = Query(default="day", max_length=8), format: str = Format,
):  # fmt: skip
    data = guard(lambda: queries.llm_tokens(session, f, granularity, r.start, r.end))
    return respond(session, data, format, "llm-tokens")


@router.get("/llm/efficiency")
def llm_efficiency(
    request: Request, session: SessionDep, settings: SettingsDep, f: Filters = FilterDep,
    r: Range = RangeDep, format: str = Format,
):  # fmt: skip
    """Cache hit rate, fallback rate and tokens per case against the target, plus today's quota gauges."""
    data = queries.llm_efficiency(session, settings, f, r.start, r.end)
    gateway = request.app.state.llm_gateway
    data["quota"] = gateway.status()["providers"]
    return respond(session, data, format, "llm-efficiency")


@router.get("/llm/cost")
def llm_cost(
    session: SessionDep,
    settings: SettingsDep,
    f: Filters = FilterDep,
    r: Range = RangeDep,
    format: str = Format,
):
    return respond(
        session, queries.llm_cost(session, settings, f, r.start, r.end), format, "llm-cost"
    )
