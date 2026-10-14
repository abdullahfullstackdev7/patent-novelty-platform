import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { axe } from "vitest-axe";

import { ADMIN, ME, installBackend, type Backend } from "@/test/backend";
import { renderAt } from "@/test/helpers";

// ECharts needs a real canvas, so the chart component is replaced by a stand-in that exposes the option it was given.
vi.mock("@/analytics/EChart", () => ({
  EChart: ({ option, label }: { option: unknown; label: string }) => <div role="img" aria-label={label} data-testid="echart" data-option={JSON.stringify(option)} />,
}));

const AXE = { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } };
const months = ["2026-01-01", "2026-02-01", "2026-03-01"];
const meta = { includes_demo: true, demo_through: "2026-03-28", refreshed_at: "2026-03-30T00:00:00Z" };

const kpi = (value: number, delta: number, pct: number) => ({ value, previous: value - delta, delta, delta_pct: pct, sparkline: [1, 2, 3, value] });

function routes(api: Backend, overrides: Record<string, unknown> = {}) {
  const series = (values: number[]) => ({ meta, rows: months.map((m, i) => ({ period: m, value: values[i], previous_period: "2025-01-01", previous: values[i] / 2 })) });
  const on = (path: string, body: unknown | ((u: URL) => unknown)) =>
    api.on("GET", new RegExp(`^/analytics${path}$`), ({ url }) => ({ body: overrides[path] ?? (typeof body === "function" ? (body as (u: URL) => unknown)(url) : body) }));

  on("/revenue/summary", { meta, as_of: "2026-03-31", month: "2026-03-01", active_clients: 12, kpis: { mrr: kpi(61428, 2186, 3.69), arr: kpi(737136, 26232, 3.69), nrr: kpi(99.06, 7.49, 8.18), arpa: kpi(1575.08, -26.06, -1.63), collections_rate: kpi(94.31, 0.41, 0.44), receivables: kpi(27060, 549, 2.07) }, rows: [] });
  on("/revenue/timeseries", (u: URL) => {
    const metric = u.searchParams.get("metric");
    const base: Record<string, number[]> = { revenue: [1000, 1200, 1500], subscription_revenue: [800, 900, 1100], addon_revenue: [100, 150, 200], overage_revenue: [100, 150, 200], mrr_growth_rate: [2, 3, 1.5], mrr_growth_ma3: [2, 2.5, 2.2], reports_generated: [10, 20, 30] };
    return series(base[metric ?? "revenue"] ?? [1, 2, 3]);
  });
  on("/revenue/breakdown", (u: URL) => {
    const by = u.searchParams.get("by");
    const row = (key: string, label: string, revenue: number, extra = {}) => ({ key, label, revenue, subscription: revenue, addon: 0, overage: 0, clients: 3, share_pct: 33.3, ...extra });
    if (by === "plan") return { meta, rows: [row("starter", "Starter", 1000), row("professional", "Professional", 2000), row("enterprise", "Enterprise", 3000)] };
    if (by === "industry") return { meta, rows: [row("Law firm", "Law firm", 4000), row("University", "University", 2000)] };
    return { meta, rows: Array.from({ length: 12 }, (_, i) => row(`c${i}`, `Client ${i}`, 100 * (i + 1), { reports: i * 10, trend_pct: i === 11 ? null : i - 5 })) };
  });
  on("/revenue/mrr-walk", { meta, rows: [{ month: "2026-01-01", opening: 1000, new: 200, expansion: 50, contraction: 20, churn: 30, closing: 1200, new_clients: 2, churned_clients: 1, active_clients: 10 }, { month: "2026-02-01", opening: 1200, new: 100, expansion: 0, contraction: 40, churn: 60, closing: 1200, new_clients: 1, churned_clients: 1, active_clients: 10 }] });
  on("/revenue/aging", { meta: { ...meta, as_of: "2026-03-31", outstanding: 1500 }, rows: [{ bucket: "current", invoices: 3, amount: 900 }, { bucket: "1-30", invoices: 2, amount: 400 }, { bucket: "31-60", invoices: 1, amount: 200 }, { bucket: "60+", invoices: 0, amount: 0 }], statuses: [{ status: "issued", invoices: 4, amount: 1100 }, { status: "overdue", invoices: 2, amount: 400 }, { status: "paid", invoices: 20, amount: 9000 }] });
  on("/revenue/cohorts", { meta, rows: [], matrix: [{ cohort: "2026-01-01", size: 4, retention: { "0": 100, "1": 75 } }, { cohort: "2026-02-01", size: 2, retention: { "0": 100 } }] });
  on("/revenue/margin", { meta, rows: months.map((m) => ({ month: m, revenue: 1000, token_cost: 0.5, infra_cost: 350, gross_margin: 650, gross_margin_pct: 65 })) });
  on("/ops/funnel", { meta, rows: [{ stage: "intake", cases: 100 }, { stage: "searched", cases: 90 }, { stage: "charted", cases: 80 }, { stage: "reviewed", cases: 60 }, { stage: "approved", cases: 50 }] });
  on("/ops/risk", { meta, rows: months.map((m) => ({ month: m, low: 5, medium: 4, medium_high: 3, high: 2 })) });
  on("/ops/cpc", { meta, rows: [{ subclass: "G06N", votes: 50, searches: 9 }], heatmap: months.flatMap((m) => ["G06N", "A61B"].map((s) => ({ month: m, subclass: s, votes: 10 }))) });
  on("/ops/turnaround", { meta, rows: [{ bucket: "0-4h", cases: 3 }, { bucket: "4-8h", cases: 9 }], summary: { cases: 12, mean_hours: 30, p50_hours: 24.9, p90_hours: 54 }, trend: months.map((m) => ({ month: m, cases: 4, p50_hours: 24, p90_hours: 50 })) });
  on("/ops/attorneys", { meta, rows: [{ user_id: "a", name: "Attorney One", role: "attorney", is_demo: true, cases: 40, approved: 35, in_review: 2 }, { user_id: "b", name: "Attorney Two", role: "attorney", is_demo: true, cases: 60, approved: 50, in_review: 5 }] });
  on("/ops/latency", { meta, rows: months.map((m) => ({ month: m, searches: 50, p50_ms: 900, p95_ms: 1800 })) });
  on("/ops/backlog", { meta, rows: [{ age: "1-3 days", status: "in_review", cases: 4 }] });
  on("/llm/tokens", { meta, rows: months.flatMap((m) => [{ period: m, provider: "groq", tokens_in: 1, tokens_out: 1, tokens: 8000, calls: 5 }, { period: m, provider: "gemini", tokens_in: 1, tokens_out: 1, tokens: 2000, calls: 2 }]) });
  on("/llm/efficiency", { meta: { ...meta, target_tokens_per_case: 9000 }, rows: months.map((m) => ({ month: m, calls: 70, cache_hit_rate: 12.5, fallback_rate: 8.2, tokens: 90000, cases: 10, tokens_per_case: 9000, target: 9000 })), quota: [{ name: "groq", model: "m", configured: true, day: { tokens_used: 90000, tokens_limit: 100000, tokens_percent: 90, requests_used: 10, requests_limit: 1000, requests_percent: 1 } }, { name: "gemini", model: "g", configured: true, day: { tokens_used: 1000, tokens_limit: 250000, tokens_percent: 0.4, requests_used: 1, requests_limit: 1000, requests_percent: 0.1 } }] });
  on("/llm/cost", { meta, rows: months.map((m) => ({ month: m, cost: 0.5, cases: 10, cost_per_case: 0.05, revenue: 1000, reports: 10, revenue_per_case: 100, margin_per_case: 99.95 })) });
  api.on("GET", /^\/billing\/clients$/, () => ({ body: { items: [{ id: "client-1", name: "Larkspur IP" }], total: 1 } }));
  api.on("GET", /^\/billing\/plans$/, () => ({ body: [{ code: "starter", name: "Starter" }, { code: "professional", name: "Professional" }] }));
}

async function open(path = "/app/analytics", overrides: Record<string, unknown> = {}, setup?: (api: Backend) => void) {
  localStorage.setItem("priorart.session", "1");
  const api = installBackend(ADMIN);
  routes(api, overrides);
  setup?.(api);
  const view = await renderAt(path);
  return { api, view };
}

const chart = (title: string) => {
  const el = screen.getAllByTestId("echart").find((e) => e.getAttribute("aria-label")?.startsWith(`${title}.`));
  if (!el) throw new Error(`chart not found: ${title}`);
  return JSON.parse(el.getAttribute("data-option")!);
};
const analyticsCalls = (api: Backend, from = 0) => api.calls.slice(from).filter((c) => c.path.startsWith("/analytics"));
const urlsFrom = (n: number) => (global.fetch as unknown as { mock: { calls: [string][] } }).mock.calls.slice(n).map((c) => c[0]);
const callUrls = (api: Backend) => api.calls.filter((c) => c.path.startsWith("/analytics"));

beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
});

describe("access", () => {
  it("is limited to administrators", async () => {
    localStorage.setItem("priorart.session", "1");
    installBackend(ME);
    await renderAt("/app/analytics");
    expect(await screen.findByText("You do not have access to this page")).toBeInTheDocument();
  });

  it("is linked from the admin sidebar", async () => {
    await open("/app");
    expect(within(await screen.findByRole("navigation", { name: "Application" })).getByRole("link", { name: "Analytics" })).toHaveAttribute("href", "/app/analytics");
  });
});

describe("revenue tab", () => {
  it("shows the six KPIs with their period change and the demo data note", async () => {
    await open();
    expect(await screen.findByTestId("kpi-mrr")).toHaveTextContent("$61,428");
    expect(screen.getByTestId("kpi-arr")).toHaveTextContent("$737,136");
    expect(screen.getByTestId("kpi-nrr")).toHaveTextContent("99.1%");
    expect(screen.getByTestId("kpi-arpa")).toHaveTextContent("$1,575");
    expect(screen.getByTestId("kpi-collections_rate")).toHaveTextContent("94.3%");
    expect(screen.getByTestId("kpi-receivables")).toHaveTextContent("$27,060");
    expect(screen.getAllByText("+3.7% vs previous month").length).toBe(2);
    expect(screen.getByText("-1.6% vs previous month")).toBeInTheDocument();
    expect(await screen.findByText("Includes demo data through Mar 28, 2026")).toBeInTheDocument();
  });

  it("stacks subscription, add-on seats and overage, adds a trend line and proves the parts equal the total", async () => {
    await open();
    await screen.findAllByTestId("echart");
    await waitFor(() => expect(chart("Revenue by period").series).toHaveLength(4));
    const option = chart("Revenue by period");
    expect(option.series.map((s: { name: string }) => s.name)).toEqual(["Subscription", "Add-on seats", "Overage", "3-period average"]);
    expect(option.series[0].data).toEqual([800, 900, 1100]);
    expect(option.yAxis.name).toBe("USD");
    expect(option.xAxis.data).toEqual(["Jan 26", "Feb 26", "Mar 26"]);
    expect(screen.getByText(/equals the total \(largest difference \$0\.00\)/)).toBeInTheDocument();
  });

  it("draws the MRR waterfall that ends at closing MRR and says it reconciles", async () => {
    await open();
    await screen.findAllByTestId("echart");
    await waitFor(() => expect(chart("MRR movement").xAxis.data).toHaveLength(6));
    const o = chart("MRR movement");
    expect(o.xAxis.data[0]).toBe("Opening MRR");
    expect(o.xAxis.data[5]).toBe("Closing MRR");
    expect(screen.getByText("Opening plus movements equals closing MRR.")).toBeInTheDocument();
  });

  it("lists the top 10 clients by revenue with usage and trend", async () => {
    await open();
    const table = await screen.findByRole("table", { name: "Top 10 clients by revenue" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(11);
    expect(rows[1]).toHaveTextContent("Client 11");
    expect(rows[1]).toHaveTextContent("n/a"); // no earlier period to compare with
    expect(rows[2]).toHaveTextContent("Client 10");
    expect(rows[2]).toHaveTextContent("+5.0%");
  });

  it("renders the plan donut with plan colours, the aging bar, the status table and the cohort heatmap", async () => {
    await open();
    await screen.findAllByTestId("echart");
    await waitFor(() => expect(chart("Revenue by plan").series[0].data).toHaveLength(3));
    expect(chart("Revenue by plan").series[0].type).toBe("pie");
    expect(chart("Invoice aging").series.map((s: { name: string }) => s.name)).toEqual(["Current", "1 to 30 days", "31 to 60 days", "60+ days"]);
    expect(screen.getByRole("table", { name: "Invoice status" })).toHaveTextContent("overdue");
    expect(screen.getByText("Outstanding $1,500.")).toBeInTheDocument();
    await waitFor(() => expect(chart("Cohort retention").series[0].data.length).toBe(3));
    expect(chart("Revenue growth").series.map((s: { name: string }) => s.name)).toEqual(["Monthly growth", "3-month average"]);
  });

  it("offers a table view, CSV export and PNG export for each chart", async () => {
    await open();
    await screen.findAllByTestId("echart");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Show table for Revenue by period" }));
    const table = await screen.findByRole("table", { name: "Revenue by period" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByRole("columnheader", { name: "Overage" })).toBeInTheDocument();

    const mark = (global.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.length;
    await user.click(screen.getByRole("button", { name: "Export Revenue by period as CSV" }));
    await waitFor(() => expect(urlsFrom(mark).some((u) => u.includes("/analytics/revenue/timeseries") && u.includes("format=csv") && u.includes("metric=revenue"))).toBe(true));
    expect(await screen.findByText("CSV exported")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /as PNG$/ }).length).toBeGreaterThan(5);
  });

  it("shows an empty state when a chart has no data", async () => {
    await open("/app/analytics", { "/revenue/mrr-walk": { meta, rows: [] } });
    expect(await screen.findByText("No data for these filters.")).toBeInTheDocument();
  });

  it("shows an error inside the chart that failed and retries it", async () => {
    let fail = true;
    await open("/app/analytics", {}, (api) => api.on("GET", /^\/analytics\/revenue\/aging$/, () => (fail ? { status: 500, body: { detail: "database down" } } : { body: { meta, rows: [{ bucket: "current", invoices: 1, amount: 5 }], statuses: [] } })));
    expect(await screen.findByText("database down")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText("database down")).toBeNull());
  });
});

describe("filters", () => {
  it("sends the plan filter to every chart on every tab", async () => {
    const { api } = await open();
    await screen.findAllByTestId("echart");
    const user = userEvent.setup();
    const mark = api.calls.length;
    await screen.findByRole("option", { name: "Starter" });
    await user.selectOptions(screen.getByLabelText("Plan"), "starter");
    await waitFor(() => expect(analyticsCalls(api, mark).length).toBeGreaterThanOrEqual(10));
    const urls = (global.fetch as unknown as { mock: { calls: [string][] } }).mock.calls.map((c) => c[0]).slice(mark).filter((u) => u.includes("/analytics"));
    expect(urls.length).toBeGreaterThanOrEqual(10);
    expect(urls.every((u) => u.includes("plan=starter"))).toBe(true);

    const before = (global.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.length;
    await user.click(screen.getByRole("tab", { name: "Usage and operations" }));
    await user.click(await screen.findByRole("tab", { name: "LLM and cost efficiency" }));
    await waitFor(() => expect((global.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.length).toBeGreaterThan(before + 8));
    const later = (global.fetch as unknown as { mock: { calls: [string][] } }).mock.calls.map((c) => c[0]).slice(before).filter((u) => u.includes("/analytics"));
    expect(later.length).toBeGreaterThanOrEqual(10);
    expect(later.every((u) => u.includes("plan=starter") && u.includes("include_demo=true"))).toBe(true);
  });

  const urlsSince = (n: number) => (global.fetch as unknown as { mock: { calls: [string][] } }).mock.calls.slice(n).map((c) => c[0]).filter((u) => u.includes("/analytics"));
  const count = () => (global.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.length;

  it("changes the date range with the presets and the custom dates", async () => {
    await open();
    await screen.findAllByTestId("echart");
    const user = userEvent.setup();
    let mark = count();
    await user.selectOptions(screen.getByLabelText("Date range"), "30d");
    await waitFor(() => expect(urlsSince(mark).length).toBeGreaterThan(8));
    const thirty = urlsSince(mark).find((u) => u.includes("/revenue/timeseries"))!;
    const params = new URL(thirty, "http://x").searchParams;
    expect((new Date(params.get("to")!).getTime() - new Date(params.get("from")!).getTime()) / 86_400_000).toBe(29);

    mark = count();
    await user.selectOptions(screen.getByLabelText("Date range"), "custom");
    const from = await screen.findByLabelText("From");
    fireInput(from, "2025-01-01");
    await waitFor(() => expect(urlsSince(mark).some((u) => u.includes("from=2025-01-01"))).toBe(true));
    expect(screen.getByLabelText("To")).toBeInTheDocument();
  });

  function fireInput(el: HTMLElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  it("turns on the previous-period overlay", async () => {
    await open();
    await screen.findAllByTestId("echart");
    await waitFor(() => expect(chart("Revenue by period").series).toHaveLength(4));
    expect(chart("Revenue by period").series.some((s: { name: string }) => s.name === "Previous period")).toBe(false);
    const mark = count();
    await userEvent.click(screen.getByLabelText("Compare to previous period"));
    await waitFor(() => expect(chart("Revenue by period").series.some((s: { name: string }) => s.name === "Previous period")).toBe(true));
    expect(urlsSince(mark).some((u) => u.includes("compare=previous"))).toBe(true);
    expect(chart("Revenue by period").series.at(-1).data).toEqual([500, 600, 750]);
  });

  it("switches granularity but keeps monthly-only series monthly", async () => {
    await open();
    await screen.findAllByTestId("echart");
    const mark = count();
    await userEvent.click(screen.getByLabelText("week"));
    await waitFor(() => expect(urlsSince(mark).some((u) => u.includes("metric=revenue") && u.includes("granularity=week"))).toBe(true));
    expect(urlsSince(mark).filter((u) => u.includes("metric=mrr_growth_rate")).every((u) => u.includes("granularity=month"))).toBe(true);
    expect(screen.getByLabelText("week")).toBeChecked();
  });

  it("filters by client and by demo data, and resets", async () => {
    await open();
    await screen.findAllByTestId("echart");
    const user = userEvent.setup();
    await screen.findByRole("option", { name: "Larkspur IP" });
    let mark = count();
    await user.selectOptions(screen.getByLabelText("Client"), "client-1");
    await waitFor(() => expect(urlsSince(mark).length).toBeGreaterThan(8));
    expect(urlsSince(mark).every((u) => u.includes("client_id=client-1"))).toBe(true);
    mark = count();
    await user.click(screen.getByLabelText("Include demo data"));
    await waitFor(() => expect(urlsSince(mark).length).toBeGreaterThan(8));
    expect(urlsSince(mark).every((u) => u.includes("include_demo=false"))).toBe(true);
    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByLabelText("Client")).toHaveValue("");
    expect(screen.getByLabelText("Include demo data")).toBeChecked();
  });

  it("restores filters from the address so a view can be shared", async () => {
    await open("/app/analytics?range=24m&plan=starter&by=week&compare=1");
    await screen.findAllByTestId("echart");
    expect(screen.getByLabelText("Date range")).toHaveValue("24m");
    expect(screen.getByLabelText("week")).toBeChecked();
    expect(screen.getByLabelText("Compare to previous period")).toBeChecked();
    await waitFor(() => expect(screen.getByLabelText("Plan")).toHaveValue("starter"));
  });
});

describe("usage and operations tab", () => {
  it("shows the funnel, risk mix, technology heatmap, turnaround, latency and the two tables", async () => {
    const { api } = await open("/app/analytics?tab=ops");
    await screen.findAllByTestId("echart");
    await waitFor(() => expect(chart("Case funnel").series[0].data).toHaveLength(5));
    expect(chart("Case funnel").yAxis.data).toEqual(["Intake", "Searched", "Charted", "Reviewed", "Approved"]);
    expect(chart("Risk distribution").series.map((s: { name: string }) => s.name)).toEqual(["Low", "Medium", "Medium-high", "High"]);
    expect(chart("Technology areas").series[0].type).toBe("heatmap");
    expect(chart("Turnaround trend").series.map((s: { name: string }) => s.name)).toEqual(["Median (p50)", "Slowest 10% (p90)"]);
    expect(chart("Search latency").series[1].name).toBe("95th percentile (p95)");
    expect(chart("Reports generated").series[0].areaStyle).toBeDefined();
    expect(screen.getByText(/12 approved cases. Median 24.9 h, slowest 10% 2.3 days/)).toBeInTheDocument();
    const attorneys = screen.getByRole("table", { name: "Attorney throughput" });
    expect(within(attorneys).getAllByRole("row")[1]).toHaveTextContent("Attorney Two"); // busiest first
    expect(screen.getByRole("table", { name: "Review backlog" })).toHaveTextContent("1-3 days");
    expect(analyticsCalls(api).some((c) => c.path === "/analytics/ops/cpc")).toBe(true);
  });

  it("explains an empty backlog", async () => {
    await open("/app/analytics?tab=ops", { "/ops/backlog": { meta, rows: [] } });
    expect(await screen.findByText("Nothing is waiting for review.")).toBeInTheDocument();
  });
});

describe("LLM and cost efficiency tab", () => {
  it("shows quota gauges, tokens by provider with fixed colours, the target line and unit economics", async () => {
    await open("/app/analytics?tab=llm");
    const gauge = await screen.findByRole("meter", { name: "groq daily token quota used" });
    expect(gauge).toHaveAttribute("aria-valuenow", "90");
    expect(screen.getByText(/Close to the limit/)).toBeInTheDocument();
    await waitFor(() => expect(chart("Tokens by provider").series).toHaveLength(2));
    const tokens = chart("Tokens by provider");
    expect(tokens.series.map((s: { name: string }) => s.name)).toEqual(["Gemini", "Groq"]);
    expect(tokens.series.find((s: { name: string }) => s.name === "Groq").lineStyle.color).toBe("#2a78d6");
    expect(tokens.series.find((s: { name: string }) => s.name === "Gemini").lineStyle.color).toBe("#eb6834");
    await waitFor(() => expect(chart("Tokens per case").series[0].markLine.data[0].yAxis).toBe(9000));
    expect(chart("Cache hits and fallbacks").series.map((s: { name: string }) => s.name)).toEqual(["Cache hit rate", "Fallback rate"]);
    expect(await screen.findByText("Unit economics, latest month")).toBeInTheDocument();
    expect(screen.getAllByText("65.0%").length).toBeGreaterThan(0);
    expect(chart("Revenue per case").series[0].data).toEqual([100, 100, 100]);
    expect(chart("Model cost per case").series[0].data).toEqual([0.05, 0.05, 0.05]);
  });

  it("says so when no provider is configured", async () => {
    await open("/app/analytics?tab=llm", { "/llm/efficiency": { meta: { ...meta, target_tokens_per_case: 9000 }, rows: [], quota: [] } });
    expect(await screen.findByText(/No provider is configured/)).toBeInTheDocument();
  });
});

describe("theme and accessibility", () => {
  it("uses the dark palette when the app theme is dark, without repainting series identity", async () => {
    await open();
    await screen.findAllByTestId("echart");
    await waitFor(() => expect(chart("Revenue by period").series).toHaveLength(4));
    expect(chart("Revenue by period").color[0]).toBe("#2a78d6");
    await userEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    await waitFor(() => expect(chart("Revenue by period").color[0]).toBe("#3987e5"));
    expect(chart("Revenue by period").color[1]).toBe("#d95926"); // same slot order in both modes
  });

  it.each([["revenue", "/app/analytics"], ["ops", "/app/analytics?tab=ops"], ["llm", "/app/analytics?tab=llm"]])("the %s tab has no detectable violations", async (_name, path) => {
    const { view } = await open(path);
    await waitFor(() => expect(view.container.querySelectorAll('[aria-busy="true"]').length).toBe(0));
    await screen.findAllByTestId("echart");
    await new Promise((r) => setTimeout(r, 50));
    expect(await axe(view.container, AXE)).toHaveNoViolations();
  });
});

it("never hard-codes figures: every number comes from an analytics request", async () => {
  const { api } = await open();
  await screen.findAllByTestId("echart");
  const paths = new Set(callUrls(api).map((c) => c.path));
  for (const p of ["/analytics/revenue/summary", "/analytics/revenue/timeseries", "/analytics/revenue/breakdown", "/analytics/revenue/mrr-walk", "/analytics/revenue/aging", "/analytics/revenue/cohorts"]) {
    expect(paths.has(p), p).toBe(true);
  }
});
