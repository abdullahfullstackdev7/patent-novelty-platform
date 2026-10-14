"""Deterministic demo history: clients, subscriptions, usage, cases, invoices and payments.

Everything is generated from one random seed, so the same configuration always produces the
same data. Rows carry `is_demo` so the dashboard can say so and so demo data can be removed
without touching real activity. Invoice amounts use the same `build_lines` as the live ledger.
"""

from __future__ import annotations

import math
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.billing.invoicing import build_lines, money
from app.billing.subscriptions import month_start, next_month, previous_month
from app.billing.views import refresh_views
from app.config import Settings
from app.db.models import (
    Case,
    Client,
    Invoice,
    InvoiceLine,
    LlmCall,
    Plan,
    ReviewEvent,
    Role,
    SearchRun,
    Subscription,
    UsageEvent,
    User,
)

SEGMENTS = (("Law firm", 0.50), ("Corporate IP team", 0.35), ("University / tech transfer", 0.15))
REGIONS = (
    ("North America", 0.50),
    ("Europe", 0.28),
    ("Asia Pacific", 0.17),
    ("Middle East and Africa", 0.05),
)
START_PLAN = {
    "Law firm": (("starter", 0.50), ("professional", 0.47), ("enterprise", 0.03)),
    "Corporate IP team": (("starter", 0.15), ("professional", 0.80), ("enterprise", 0.05)),
    "University / tech transfer": (("starter", 0.70), ("professional", 0.30)),
}
UTILIZATION = {
    "starter": 0.95,
    "professional": 0.62,
    "enterprise": 0.45,
}  # share of included reports
CHURN = {"starter": 0.022, "professional": 0.012, "enterprise": 0.005}
UPGRADE = {"starter": ("professional", 0.025), "professional": ("enterprise", 0.012)}
DOWNGRADE = {"professional": ("starter", 0.006), "enterprise": ("professional", 0.008)}
SEASONALITY = (1.0, 1.0, 1.1, 1.0, 0.95, 0.9, 0.8, 0.8, 1.0, 1.1, 1.15, 1.05)  # January to December
CPC_AREAS = {
    "Law firm": ("G06N", "G06F", "H04L", "G06Q", "H04W", "A61B"),
    "Corporate IP team": ("H01M", "B60L", "G06N", "H04W", "A61B", "G06F"),
    "University / tech transfer": ("C12N", "A61B", "G16H", "G06N", "H01M", "G06F"),
}
RISK_LEVELS = (
    ("low", 0.40, (0, 35)),
    ("medium", 0.25, (36, 64)),
    ("medium_high", 0.20, (65, 84)),
    ("high", 0.15, (85, 100)),
)
WORDS_A = ("Northwind", "Larkspur", "Cobalt", "Harbor", "Juniper", "Meridian", "Silverleaf", "Alder", "Brightwater",
           "Copperfield", "Dunmore", "Evergreen", "Foxglove", "Granite", "Hollis", "Ironbridge", "Kestrel", "Linden")  # fmt: skip
WORDS_B = {"Law firm": ("IP Partners", "Patent Group", "Legal LLP", "Intellectual Property"),
           "Corporate IP team": ("Technologies IP Office", "Industries Patent Team", "Systems IP Counsel"),
           "University / tech transfer": ("University Technology Transfer", "Institute Innovation Office")}  # fmt: skip


@dataclass
class SeedConfig:
    seed: int = 20260101
    clients: int = 48
    months: int = 24
    as_of: date | None = None  # history ends the day before this date
    ops: bool = True  # also create cases, reviews, search runs and LLM calls
    start_clients: int = 8


@dataclass
class SeedReport:
    clients: int = 0
    subscriptions: int = 0
    usage_events: int = 0
    cases: int = 0
    invoices: int = 0
    invoice_lines: int = 0
    llm_calls: int = 0
    first_month: date | None = None
    last_month: date | None = None
    notes: list[str] = field(default_factory=list)


class Rng:
    """random.Random with a few helpers, so seeds stay reproducible."""

    def __init__(self, seed: int) -> None:
        self.r = random.Random(seed)

    def uuid(self) -> uuid.UUID:
        return uuid.UUID(bytes=self.r.randbytes(16), version=4)

    def pick(self, weighted: tuple[tuple[str, float], ...]) -> str:
        return self.r.choices([k for k, _ in weighted], [w for _, w in weighted])[0]

    def chance(self, p: float) -> bool:
        return self.r.random() < p

    def lognormal(self, median: float, sigma: float) -> float:
        return math.exp(math.log(median) + self.r.gauss(0, sigma))


def purge_demo_data(session: Session) -> None:
    """Remove every demo row. Real clients, cases and users are left alone."""
    demo_clients = "(SELECT id FROM clients WHERE is_demo)"
    for sql in (
        f"DELETE FROM invoice_lines WHERE invoice_id IN (SELECT id FROM invoices WHERE client_id IN {demo_clients})",
        f"DELETE FROM invoices WHERE client_id IN {demo_clients}",
        f"DELETE FROM usage_events WHERE is_demo OR client_id IN {demo_clients}",
        f"DELETE FROM subscriptions WHERE client_id IN {demo_clients}",
        "DELETE FROM llm_calls WHERE case_id IN (SELECT id FROM cases WHERE is_demo)",
        "DELETE FROM cases WHERE is_demo",
        "DELETE FROM users WHERE is_demo",
        "DELETE FROM clients WHERE is_demo",
    ):
        session.execute(text(sql))


def _bulk(session: Session, model, items: list[dict], chunk: int = 2000) -> None:
    for start in range(0, len(items), chunk):
        session.execute(insert(model), items[start : start + chunk])


def _client_names(rng: Rng, segment: str, used: set[str]) -> str:
    for _ in range(50):
        name = f"{rng.r.choice(WORDS_A)} {rng.r.choice(WORDS_B[segment])}"
        if name not in used:
            used.add(name)
            return name
    name = f"{rng.r.choice(WORDS_A)} {rng.r.choice(WORDS_B[segment])} {len(used) + 1}"
    used.add(name)
    return name


@dataclass
class _Segment:
    start: date
    plan: str
    seats: int
    end: date | None = None


def _simulate_client(
    rng: Rng, segment: str, signup: date, last: date, plans: dict[str, Plan]
) -> list[_Segment]:
    """Subscription history: plan changes, seat additions, churn and the odd comeback."""
    plan = rng.pick(START_PLAN[segment])
    current = _Segment(signup, plan, plans[plan].seats)
    segments = [current]
    month = next_month(signup)
    while month <= last:
        if rng.chance(CHURN[current.plan]):
            current.end = month
            if not rng.chance(0.12):  # 12 percent come back after a break
                return segments
            month = next_month(next_month(next_month(month)))
            if month > last:
                return segments
            current = _Segment(month, current.plan, plans[current.plan].seats)
            segments.append(current)
        else:
            new_plan, seats = current.plan, current.seats
            up, down = UPGRADE.get(current.plan), DOWNGRADE.get(current.plan)
            if up and rng.chance(up[1]):
                new_plan, seats = up[0], max(plans[up[0]].seats, seats)
            elif down and rng.chance(down[1]):
                new_plan, seats = down[0], min(seats, plans[down[0]].seats * 2)
            elif seats < plans[current.plan].seats * 2 and rng.chance(0.04):
                seats += rng.r.randint(1, 3)
            if (new_plan, seats) != (current.plan, current.seats):
                current.end = month
                current = _Segment(month, new_plan, seats)
                segments.append(current)
        month = next_month(month)
    return segments


def seed_business_data(
    sessions: sessionmaker[Session], settings: Settings, config: SeedConfig | None = None
) -> SeedReport:
    config = config or SeedConfig()
    rng = Rng(config.seed)
    as_of = config.as_of or date.today()
    current_month = month_start(as_of)
    first_month = current_month
    for _ in range(config.months):
        first_month = previous_month(first_month)
    last_history_month = previous_month(current_month)
    history = []
    cursor = first_month
    while cursor <= last_history_month:
        history.append(cursor)
        cursor = next_month(cursor)
    cutoff = datetime.combine(
        as_of - timedelta(days=1), datetime.max.time(), tzinfo=UTC
    )  # nothing from "today"
    report = SeedReport(first_month=first_month, last_month=last_history_month)

    with sessions() as session:
        purge_demo_data(session)
        plans = {p.code: p for p in session.scalars(select(Plan))}
        if not {"starter", "professional", "enterprise"} <= set(plans):
            raise RuntimeError("the reference plans are missing, run the migrations first")
        roles = {r.name: r.id for r in session.scalars(select(Role))}

        # ---- clients --------------------------------------------------------------------------------------------
        weights = [1 + 1.5 * i / max(len(history) - 1, 1) for i in range(len(history))]
        signup_index = [0] * min(config.start_clients, config.clients)
        signup_index += rng.r.choices(
            range(len(history)), weights, k=config.clients - len(signup_index)
        )
        signup_index.sort()
        used_names: set[str] = set()
        clients, users, segments_by_client, payer = [], [], {}, {}
        for index, month_index in enumerate(signup_index):
            segment = rng.pick(SEGMENTS)
            client_id = rng.uuid()
            signup = history[month_index]
            clients.append({"id": client_id, "name": _client_names(rng, segment, used_names), "industry": segment,
                            "region": rng.pick(REGIONS), "segment": segment, "is_demo": True,
                            "signed_up_on": signup})  # fmt: skip
            segments_by_client[client_id] = _simulate_client(
                rng, segment, signup, last_history_month, plans
            )
            payer[client_id] = rng.pick((("prompt", 0.6), ("average", 0.3), ("slow", 0.1)))
            for role, label in (("attorney", "Attorney"), ("analyst", "Analyst")):
                users.append({"id": rng.uuid(), "email": f"demo-{index + 1}-{role}@demo.invalid",
                              "full_name": f"{label} {index + 1} (demo)", "role_id": roles[role], "client_id": client_id,
                              "is_active": True, "password_hash": None, "is_demo": True})  # fmt: skip
        _bulk(session, Client, clients)
        if config.ops:
            _bulk(session, User, users)
        users_by_client: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for user in users:
            users_by_client[user["client_id"]].append(user["id"])
        segment_of = {c["id"]: c["segment"] for c in clients}
        report.clients = len(clients)

        # ---- subscriptions -----------------------------------------------------------------------------------------
        subscriptions = []
        for client_id, segs in segments_by_client.items():
            for seg in segs:
                subscriptions.append({"id": rng.uuid(), "client_id": client_id, "plan_id": plans[seg.plan].id,
                                      "status": "cancelled" if seg.end else "active", "seats": seg.seats,
                                      "started_on": seg.start, "ended_on": seg.end})  # fmt: skip
        _bulk(session, Subscription, subscriptions)
        report.subscriptions = len(subscriptions)
        sub_for: dict[tuple[uuid.UUID, date], dict] = {}
        for sub in subscriptions:  # the subscription active at the end of each history month
            for month in history:
                last_day = next_month(month) - timedelta(days=1)
                if sub["started_on"] <= last_day and (
                    sub["ended_on"] is None or sub["ended_on"] > last_day
                ):
                    sub_for[(sub["client_id"], month)] = sub
        plan_by_id = {p.id: p for p in plans.values()}

        # ---- usage, cases and operational history ---------------------------------------------------------------------
        usage, cases, reviews, searches, llm_calls = [], [], [], [], []
        used_in: dict[tuple[uuid.UUID, date], int] = defaultdict(int)
        total_months = max(len(history) - 1, 1)
        for (client_id, month), sub in sorted(
            sub_for.items(), key=lambda kv: (kv[0][1], str(kv[0][0]))
        ):
            plan = plan_by_id[sub["plan_id"]]
            age = (
                (month.year - segments_by_client[client_id][0].start.year) * 12
                + month.month
                - segments_by_client[client_id][0].start.month
            )
            ramp = 0.5 if age == 0 else 0.8 if age == 1 else 1.0
            factor = (
                max(0.05, min(1.6, rng.r.gauss(UTILIZATION[plan.code], 0.28)))
                * SEASONALITY[month.month - 1]
                * ramp
            )
            count = max(0, round(plan.included_reports * factor))
            progress = (history.index(month)) / total_months
            for _ in range(count):
                moment = datetime.combine(month + timedelta(days=rng.r.randint(0, 27)), datetime.min.time(), tzinfo=UTC) + timedelta(
                    hours=rng.r.randint(8, 17), minutes=rng.r.randint(0, 59), seconds=rng.r.randint(0, 59))  # fmt: skip
                if moment > cutoff:
                    continue
                used_in[(client_id, month)] += 1
                case_id = rng.uuid() if config.ops else None
                usage.append({"client_id": client_id, "case_id": case_id, "plan_id": plan.id, "event_type": "report_generated",
                              "units": Decimal(1), "is_demo": True, "occurred_at": moment})  # fmt: skip
                if config.ops:
                    _ops_rows(rng, case_id, client_id, segment_of[client_id], users_by_client[client_id], moment, progress,
                              as_of, cases, reviews, searches, llm_calls)  # fmt: skip
        if config.ops:
            _bulk(session, Case, cases)
        _bulk(session, UsageEvent, usage)
        if config.ops:
            _bulk(session, SearchRun, searches)
            _bulk(session, ReviewEvent, reviews)
            _bulk(session, LlmCall, llm_calls)
        report.usage_events, report.cases, report.llm_calls = len(usage), len(cases), len(llm_calls)

        # ---- invoices and payments ---------------------------------------------------------------------------------------
        invoices, lines = [], []
        sequence: dict[date, int] = defaultdict(int)
        for (client_id, month), sub in sorted(
            sub_for.items(), key=lambda kv: (kv[0][1], str(kv[0][0]))
        ):
            plan = plan_by_id[sub["plan_id"]]
            sequence[month] += 1
            issued = next_month(month)
            due = issued + timedelta(days=settings.invoice_due_days)
            status, paid_on = _payment(rng, payer[client_id], issued, due, as_of)
            invoice_id = rng.uuid()
            drafts = build_lines(plan, sub["seats"], used_in.get((client_id, month), 0), month)
            for line in drafts:
                lines.append({"invoice_id": invoice_id, "kind": line.kind, "description": line.description,
                              "quantity": line.quantity, "unit_price": line.unit_price, "amount": line.amount})  # fmt: skip
            invoices.append({"id": invoice_id, "number": f"INV-{month:%Y%m}-{sequence[month]:04d}", "client_id": client_id,
                             "subscription_id": sub["id"], "period_start": month,
                             "period_end": issued - timedelta(days=1), "issued_on": issued, "due_on": due,
                             "paid_on": paid_on, "status": status,
                             "total": money(sum((d.amount for d in drafts), Decimal(0)))})  # fmt: skip
        _bulk(session, Invoice, invoices)
        _bulk(session, InvoiceLine, lines)
        report.invoices, report.invoice_lines = len(invoices), len(lines)
        refresh_views(session)
        session.commit()
    return report


def _payment(rng: Rng, kind: str, issued: date, due: date, as_of: date) -> tuple[str, date | None]:
    """Invoice status and payment date for one invoice, relative to `as_of`."""
    if rng.chance(0.01):
        return "void", None
    if rng.chance(0.008):  # written off: never paid
        return ("overdue" if due < as_of else "issued"), None
    median, sigma = {"prompt": (14, 0.35), "average": (28, 0.4), "slow": (52, 0.45)}[kind]
    delay = max(3, round(rng.lognormal(median, sigma)))
    paid = issued + timedelta(days=min(delay, 150))
    if paid < as_of:
        return "paid", paid
    return ("overdue" if due < as_of else "issued"), None


def _ops_rows(
    rng,
    case_id,
    client_id,
    segment,
    user_ids,
    moment,
    progress,
    as_of,
    cases,
    reviews,
    searches,
    llm_calls,
) -> None:
    """The case and its review, search and LLM history for one report."""
    owner = rng.r.choice(user_ids)
    attorney = user_ids[0]
    age_days = (as_of - moment.date()).days
    roll = rng.r.random()
    if age_days > 14:
        status = "approved" if roll < 0.94 else "draft"
    else:
        status = "approved" if roll < 0.55 else "in_review" if roll < 0.80 else "draft"
    level = rng.pick(tuple((name, weight) for name, weight, _ in RISK_LEVELS))
    band = next(b for name, _, b in RISK_LEVELS if name == level)
    submitted = moment + timedelta(hours=rng.r.uniform(1, 6))
    cases.append({"id": case_id, "client_id": client_id, "owner_id": owner, "title": f"[demo] Disclosure {str(case_id)[:8]}",
                  "status": status, "stage": "done", "risk_level": level, "risk_score": Decimal(rng.r.randint(*band)),
                  "jurisdiction": "US", "llm_mode": "auto", "confidential": True, "is_demo": True,
                  "created_at": moment, "updated_at": submitted})  # fmt: skip
    if status in ("approved", "in_review"):
        reviews.append(
            {
                "case_id": case_id,
                "user_id": owner,
                "event_type": "submitted",
                "created_at": submitted,
            }
        )
    if status == "approved":
        hours = min(rng.lognormal(26, 0.6), 240) * (
            1.15 - 0.3 * progress
        )  # reviews get faster over time
        reviews.append({"case_id": case_id, "user_id": attorney, "event_type": "approved",
                        "created_at": moment + timedelta(hours=max(hours, 2))})  # fmt: skip

    areas = list(CPC_AREAS[segment])
    rng.r.shuffle(areas)
    total_ms = rng.lognormal(950, 0.35) * (1.2 - 0.35 * progress)
    searches.append({"id": rng.uuid(), "case_id": case_id,
                     "params": {"demo": True}, "status": "done", "created_at": moment + timedelta(minutes=1),
                     "suggested_cpc": [{"subclass": a, "votes": rng.r.randint(3, 12)} for a in areas[: rng.r.randint(2, 4)]],
                     "timings_ms": {"total": round(total_ms, 1), "embed": round(total_ms * 0.15, 1),
                                    "retrieve": round(total_ms * 0.55, 1), "rerank": round(total_ms * 0.3, 1)}})  # fmt: skip

    scale = 1.15 - 0.30 * progress  # prompts get leaner over time
    fallback = 0.08 + 0.10 * rng.r.random() * (1 - progress)
    for task, tin, tout, share in (
        ("parse_elements", 900, 250, 0.4),
        ("chart_cells", 1500, 320, 1.0),
        ("exec_summary", 750, 360, 1.0),
    ):
        if rng.r.random() > share:
            continue
        stamp = moment + timedelta(minutes=2, seconds=rng.r.randint(0, 40))
        if rng.chance(0.12):  # answered from the cache
            llm_calls.append({"case_id": case_id, "task": task, "provider": "cache", "model": "cache", "tokens_in": 0,
                              "tokens_out": 0, "cached_tokens": 0, "latency_ms": 4, "status": "ok", "cache_hit": True,
                              "created_at": stamp})  # fmt: skip
            continue
        provider = "gemini" if rng.chance(fallback) else "groq"
        llm_calls.append({"case_id": case_id, "task": task, "provider": provider,
                          "model": "gemini-3.1-flash-lite" if provider == "gemini" else "openai/gpt-oss-20b",
                          "tokens_in": max(100, round(rng.r.gauss(tin, tin * 0.2) * scale)),
                          "tokens_out": max(50, round(rng.r.gauss(tout, tout * 0.2))), "cached_tokens": 0,
                          "latency_ms": round(rng.lognormal(1400, 0.4)), "status": "ok", "cache_hit": False,
                          "created_at": stamp})  # fmt: skip
