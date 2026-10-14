"""Generate 24 months of demo business history (clients, subscriptions, usage, invoices).

    uv run --project backend python scripts/seed_business_data.py
    uv run --project backend python scripts/seed_business_data.py --clients 60 --months 24
    uv run --project backend python scripts/seed_business_data.py --purge     # remove demo data only

Deterministic: the same --seed and options always give the same rows. Every row is flagged
is_demo, so the dashboard can label it and --purge removes it without touching real activity.
Run `alembic upgrade head` first (it also creates the three reference plans).
"""

from __future__ import annotations

import argparse
import time
from datetime import date

from app.billing.seed import SeedConfig, purge_demo_data, seed_business_data
from app.config import get_settings
from app.db.session import make_engine, make_session_factory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=SeedConfig.seed)
    parser.add_argument("--clients", type=int, default=48, help="40 to 60 for the standard demo")
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument(
        "--as-of", type=date.fromisoformat, help="history ends the day before this date"
    )
    parser.add_argument(
        "--no-ops", action="store_true", help="skip cases, reviews, searches and LLM calls"
    )
    parser.add_argument("--purge", action="store_true", help="only remove demo data")
    args = parser.parse_args()

    settings = get_settings()
    sessions = make_session_factory(make_engine(settings.database_url))
    if args.purge:
        with sessions() as session:
            purge_demo_data(session)
            session.commit()
        print("demo data removed")
        return
    started = time.perf_counter()
    report = seed_business_data(
        sessions, settings,
        SeedConfig(seed=args.seed, clients=args.clients, months=args.months, as_of=args.as_of, ops=not args.no_ops),
    )  # fmt: skip
    print(
        f"seeded {report.first_month} to {report.last_month} in {time.perf_counter() - started:.1f}s"
    )
    for name in (
        "clients",
        "subscriptions",
        "usage_events",
        "cases",
        "invoices",
        "invoice_lines",
        "llm_calls",
    ):
        print(f"  {name:<14}{getattr(report, name):>8,}")


if __name__ == "__main__":
    main()
