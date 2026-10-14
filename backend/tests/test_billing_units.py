"""Billing building blocks without a database: dates, ledger math, costing, CSV, seed rules."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.v1.analytics import to_csv
from app.billing import costing, queries
from app.billing.invoicing import build_lines, money
from app.billing.queries import Filters
from app.billing.seed import Rng, _payment, _simulate_client
from app.billing.subscriptions import month_start, next_month, previous_month
from app.config import Settings

S = Settings(jwt_secret="x" * 40, fernet_key="x")


def plan(code="professional", price="1490.00", included=50, overage="30.00", seats=10, extra="59.00"):
    return SimpleNamespace(code=code, name=code.title(), monthly_price=Decimal(price), included_reports=included,
                           overage_price=Decimal(overage), seats=seats, extra_seat_price=Decimal(extra))  # fmt: skip


# ---- calendar helpers -------------------------------------------------------------------------------


def test_month_helpers_cross_year_boundaries():
    assert month_start(date(2026, 10, 14)) == date(2026, 10, 1)
    assert next_month(date(2026, 12, 31)) == date(2027, 1, 1)
    assert next_month(date(2026, 2, 28)) == date(2026, 3, 1)
    assert previous_month(date(2026, 1, 15)) == date(2025, 12, 1)
    assert previous_month(date(2026, 3, 1)) == date(2026, 2, 1)
    d = date(2024, 1, 31)
    for _ in range(30):
        assert previous_month(next_month(d)) == month_start(d)
        d = next_month(d)


def test_bucket_helpers_match_postgres_date_trunc():
    wednesday = date(2026, 10, 14)
    assert queries.bucket_start(wednesday, "week") == date(2026, 10, 12)  # Monday, like date_trunc('week')
    assert queries.bucket_start(wednesday, "month") == date(2026, 10, 1)
    assert queries.bucket_start(wednesday, "day") == wednesday
    assert queries.bucket_end(date(2026, 2, 1), "month") == date(2026, 2, 28)
    assert queries.bucket_end(date(2026, 10, 12), "week") == date(2026, 10, 18)
    assert queries.step(date(2026, 1, 1), "month", -2) == date(2025, 11, 1)
    assert queries.step(date(2026, 10, 12), "week", 2) == date(2026, 10, 26)
    assert queries.step(date(2026, 10, 12), "day", -12) == date(2026, 9, 30)


def test_buckets_cover_the_range_without_gaps():
    months = queries.buckets(date(2025, 11, 20), date(2026, 2, 3), "month")
    assert months == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]
    weeks = queries.buckets(date(2026, 10, 1), date(2026, 10, 31), "week")
    assert weeks[0] == date(2026, 9, 28) and weeks[-1] == date(2026, 10, 26)
    assert all(b - a == timedelta(days=7) for a, b in zip(weeks, weeks[1:], strict=False))
    assert len(queries.buckets(date(2026, 10, 1), date(2026, 10, 31), "day")) == 31
    assert queries.buckets(date(2026, 10, 5), date(2026, 10, 5), "day") == [date(2026, 10, 5)]
    with pytest.raises(ValueError, match="granularity"):
        queries.check_unit("year")


def test_filters_become_bind_parameters():
    assert Filters().params() == {"include_demo": True, "client_id": None, "plan": None}
    import uuid

    cid = uuid.uuid4()
    assert Filters(False, cid, "starter").params() == {"include_demo": False, "client_id": str(cid), "plan": "starter"}


# ---- ledger arithmetic ------------------------------------------------------------------------------------


def test_money_rounds_half_up_to_cents():
    assert money(Decimal("1.005")) == Decimal("1.01")
    assert money(10) == Decimal("10.00")
    assert money(Decimal("2.345")) == Decimal("2.35")
    assert money(0.1 + 0.2) == Decimal("0.30")


def test_invoice_lines_subscription_only_within_the_allowance():
    lines = build_lines(plan(), seats=10, reports_used=50, period=date(2026, 9, 1))
    assert [(line.kind, line.amount) for line in lines] == [("subscription", Decimal("1490.00"))]
    assert "September 2026" in lines[0].description and "Professional plan" in lines[0].description


def test_invoice_lines_add_overage_and_extra_seats():
    lines = build_lines(plan(), seats=13, reports_used=57, period=date(2026, 9, 1))
    by_kind = {line.kind: line for line in lines}
    assert by_kind["subscription"].amount == Decimal("1490.00")
    assert by_kind["addon"].quantity == 3 and by_kind["addon"].amount == Decimal("177.00")  # 3 x 59
    assert by_kind["overage"].quantity == 7 and by_kind["overage"].amount == Decimal("210.00")  # 7 x 30
    assert "57 used" in by_kind["overage"].description
    assert sum(line.amount for line in lines) == Decimal("1877.00")


def test_invoice_lines_skip_zero_quantities_and_free_seats():
    assert len(build_lines(plan(), 10, 0, date(2026, 1, 1))) == 1
    free = build_lines(plan(extra="0.00"), seats=20, reports_used=0, period=date(2026, 1, 1))
    assert [line.kind for line in free] == ["subscription"]  # no add-on line at a zero seat price
    over = build_lines(plan(), seats=3, reports_used=51, period=date(2026, 1, 1))
    assert [line.kind for line in over] == ["subscription", "overage"]  # fewer seats than allowed is fine


def test_amounts_are_always_quantity_times_price_in_cents():
    for used in range(0, 200, 7):
        for line in build_lines(plan(overage="33.33"), 12, used, date(2026, 5, 1)):
            assert line.amount == money(line.quantity * line.unit_price)
            assert line.amount == line.amount.quantize(Decimal("0.01"))


# ---- costing ------------------------------------------------------------------------------------------------


def test_token_cost_uses_the_reference_prices_per_million_tokens():
    assert costing.token_cost(S, "groq", 1_000_000, 0) == pytest.approx(0.075)
    assert costing.token_cost(S, "groq", 0, 1_000_000) == pytest.approx(0.30)
    assert costing.token_cost(S, "gemini", 2_000_000, 1_000_000) == pytest.approx(0.20 + 0.40)
    assert costing.token_cost(S, "cache", 5_000_000, 5_000_000) == 0.0
    assert costing.token_cost(S, "groq", 6000, 2000) == pytest.approx((6000 * 0.075 + 2000 * 0.30) / 1e6)


def test_price_params_and_sql_expression_agree():
    params = costing.price_params(S)
    assert set(params) == {"g_in", "g_out", "m_in", "m_out"}
    for name in params:
        assert f":{name}" in costing.TOKEN_COST_SQL
    assert "l.provider" in costing.TOKEN_COST_SQL and "1000000.0" in costing.TOKEN_COST_SQL


# ---- CSV export ----------------------------------------------------------------------------------------------


def test_csv_neutralizes_spreadsheet_formulas_and_keeps_numbers():
    csv_text = to_csv([
        {"client": "=HYPERLINK(\"http://evil\",\"x\")", "revenue": -12.5, "note": "+1 call"},
        {"client": "@SUM(A1)", "revenue": 3, "note": "-cmd"},
        {"client": "Ordinary LLP", "revenue": None, "note": "a, b"},
    ])  # fmt: skip
    lines = csv_text.splitlines()
    assert lines[0] == "client,revenue,note"
    assert "\"'=HYPERLINK" in lines[1] and ",-12.5," in lines[1] and "'+1 call" in lines[1]  # text escaped, number kept
    assert lines[2].startswith("'@SUM") and "'-cmd" in lines[2]
    assert lines[3] == 'Ordinary LLP,,"a, b"'


def test_csv_columns_are_the_union_of_all_rows_and_empty_input_is_safe():
    assert to_csv([{"a": 1}, {"a": 2, "b": 3}]).splitlines() == ["a,b", "1,", "2,3"]
    assert to_csv([]) == "\n"


# ---- seed rules -----------------------------------------------------------------------------------------------------


def test_rng_is_reproducible_per_seed():
    a, b, c = Rng(5), Rng(5), Rng(6)
    assert [a.uuid() for _ in range(3)] == [b.uuid() for _ in range(3)]
    assert a.uuid() != c.uuid()
    picks = lambda r: [r.pick((("x", 0.5), ("y", 0.5))) for _ in range(20)]  # noqa: E731
    assert picks(Rng(1)) == picks(Rng(1)) and picks(Rng(1)) != picks(Rng(2))
    assert Rng(9).lognormal(26, 0.6) == Rng(9).lognormal(26, 0.6)


def test_payment_outcomes_are_consistent_with_the_as_of_date():
    plans_fixture = {"prompt": 0, "average": 0, "slow": 0}
    as_of = date(2026, 10, 14)
    seen = set()
    for seed in range(400):
        rng = Rng(seed)
        kind = ("prompt", "average", "slow")[seed % 3]
        issued = date(2026, 1, 1) + timedelta(days=seed % 280)
        due = issued + timedelta(days=30)
        status, paid_on = _payment(rng, kind, issued, due, as_of)
        seen.add(status)
        plans_fixture[kind] += 1
        if status == "paid":
            assert paid_on is not None and issued < paid_on < as_of
        else:
            assert paid_on is None
        if status == "overdue":
            assert due < as_of
        if status == "issued":
            assert due >= as_of
    assert seen == {"paid", "issued", "overdue", "void"} or {"paid", "overdue"} <= seen


def test_payers_differ_in_how_late_they_pay():
    as_of = date(2030, 1, 1)  # far in the future so every invoice is paid, giving the delay
    def median_delay(kind):
        delays = sorted(
            (paid - date(2026, 1, 1)).days
            for seed in range(300)
            if (paid := _payment(Rng(seed), kind, date(2026, 1, 1), date(2026, 1, 31), as_of)[1])
        )
        return delays[len(delays) // 2]
    assert median_delay("prompt") < median_delay("average") < median_delay("slow")


def test_simulated_subscription_history_is_well_formed():
    plans = {c: SimpleNamespace(seats=s) for c, s in (("starter", 3), ("professional", 10), ("enterprise", 50))}
    last = date(2026, 9, 1)
    produced_churn = produced_change = False
    for seed in range(120):
        segments = _simulate_client(Rng(seed), "Law firm", date(2024, 10, 1), last, plans)
        assert segments[0].start == date(2024, 10, 1)
        for seg in segments:
            assert seg.plan in plans and seg.seats >= 1
            assert seg.start == month_start(seg.start) and (seg.end is None or seg.end > seg.start)
        for earlier, later in zip(segments, segments[1:], strict=False):
            assert earlier.end is not None and earlier.end <= later.start  # no overlap, a gap means a break
            produced_change |= earlier.end == later.start
            produced_churn |= earlier.end < later.start
        assert all(s.end is not None for s in segments[:-1])
        assert segments[-1].end is None or segments[-1].end <= next_month(last)
    assert produced_change and produced_churn  # upgrades or seat changes and comebacks both occur


def test_simulation_is_deterministic_and_seed_sensitive():
    plans = {c: SimpleNamespace(seats=s) for c, s in (("starter", 3), ("professional", 10), ("enterprise", 50))}
    run = lambda seed: [(s.start, s.plan, s.seats, s.end) for s in  # noqa: E731
                        _simulate_client(Rng(seed), "Corporate IP team", date(2025, 1, 1), date(2026, 9, 1), plans)]
    assert run(3) == run(3)
    assert any(run(seed) != run(3) for seed in range(4, 12))
