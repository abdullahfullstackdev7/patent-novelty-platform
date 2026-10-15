"""Load test: 20 concurrent users on case, search-result and analytics endpoints.

    uv run --project backend locust -f loadtest/locustfile.py --headless -u 20 -r 5 -t 60s \
        --host http://localhost:8765 --csv loadtest/results

Accounts come from scripts/seed_demo_users.py (set LOAD_PASSWORD_PREFIX if you changed it). Half of
the virtual users read the analytics queries behind the dashboard; the other half read cases,
search results and charts. Both sign in as the admin, who can see every seeded case. Only reads are sent,
so the run can be repeated against a demo database. The login endpoint is rate limited per address,
so raise RATE_LIMIT_AUTH on the server for the run (all virtual users share one address).
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

PREFIX = os.environ.get("LOAD_PASSWORD_PREFIX", "Atlas-Demo-Harbor")
DOMAIN = os.environ.get("LOAD_EMAIL_DOMAIN", "priorart-demo.example.com")
WORDS = {"admin": "Quartz"}
RANGE = {"from": os.environ.get("LOAD_FROM", "2024-10-01"), "to": os.environ.get("LOAD_TO", "2026-09-30")}

ANALYTICS = (
    ("/analytics/revenue/summary", {"as_of": RANGE["to"]}),
    ("/analytics/revenue/timeseries", {"metric": "revenue", "granularity": "month", "compare": "previous"}),
    ("/analytics/revenue/breakdown", {"by": "plan"}),
    ("/analytics/revenue/breakdown", {"by": "client"}),
    ("/analytics/revenue/mrr-walk", {}),
    ("/analytics/revenue/aging", {"as_of": RANGE["to"]}),
    ("/analytics/revenue/cohorts", {}),
    ("/analytics/ops/funnel", {}),
    ("/analytics/ops/risk", {}),
    ("/analytics/ops/cpc", {"limit": 12}),
    ("/analytics/ops/turnaround", {}),
    ("/analytics/llm/tokens", {"granularity": "month"}),
    ("/analytics/llm/efficiency", {}),
    ("/analytics/llm/cost", {}),
)


class SignedInUser(HttpUser):
    abstract = True
    wait_time = between(0.5, 2.0)
    role = "attorney"

    def on_start(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": f"{self.role}@{DOMAIN}", "password": f"{PREFIX}-{WORDS[self.role]}-2026"},
            name="POST /auth/login",
        )
        response.raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

    def get(self, path: str, params: dict | None = None, name: str | None = None):
        return self.client.get(f"/api/v1{path}", params=params, name=name or f"GET {path}")


class AnalyticsUser(SignedInUser):
    weight = 1
    role = "admin"

    @task(5)
    def dashboard_query(self) -> None:
        path, params = random.choice(ANALYTICS)
        label = params.get("by") or params.get("metric") or ""
        self.get(path, {**RANGE, **params}, name=f"GET {path} {label}".strip())

    @task(1)
    def whole_revenue_tab(self) -> None:
        for path, params in ANALYTICS[:7]:
            self.get(path, {**RANGE, **params}, name="GET revenue tab queries")

    @task(1)
    def billing_lists(self) -> None:
        self.get("/billing/invoices", {"limit": 50})
        self.get("/billing/clients", {"include_demo": "true", "limit": 50})


class CaseUser(SignedInUser):
    weight = 1
    role = "admin"  # sees every seeded case, which belong to the demo attorneys
    case_ids: list[str]

    def on_start(self) -> None:
        super().on_start()
        listing = self.get("/cases", {"limit": 50}).json()
        self.case_ids = [c["id"] for c in listing.get("items", [])]

    @task(3)
    def list_cases(self) -> None:
        self.get("/cases", {"limit": 50})

    @task(4)
    def open_case_views(self) -> None:
        if not self.case_ids:
            return
        case_id = random.choice(self.case_ids)
        self.get(f"/cases/{case_id}", name="GET /cases/{id}")
        self.get(f"/cases/{case_id}/results", name="GET /cases/{id}/results (search results)")
        self.get(f"/cases/{case_id}/chart", name="GET /cases/{id}/chart")

    @task(1)
    def public_pages(self) -> None:
        self.get("/public/plans")
        self.get("/public/stats")
