import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";
import { useMemo } from "react";

import { ChartCard } from "@/analytics/ChartCard";
import { axisStyle, baseOption, usePalette } from "@/analytics/chartkit";
import { useAnalytics, type AgingResponse, type BreakdownRow, type CohortResponse, type KpiSummary, type Rows, type SeriesPoint, type WalkRowApi } from "@/analytics/data";
import {
  allowedGranularity,
  cohortCells,
  csvName,
  deltaText,
  effectiveGranularity,
  filterQuery,
  fmtCompactMoney,
  fmtInt,
  fmtMoney,
  fmtPct,
  formatKpi,
  maxGap,
  movingAverage,
  periodLabel,
  rangeOf,
  round2,
  sum,
  waterfall,
  type AnalyticsFilters,
  type KpiFormat,
} from "@/analytics/logic";
import { PLAN_SLOT } from "@/analytics/theme";
import { Badge, Card, CardContent, Skeleton } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export interface TabProps {
  filters: AnalyticsFilters;
  today: Date;
}

const KPIS: { key: keyof KpiSummary["kpis"]; label: string; format: KpiFormat; hint: string }[] = [
  { key: "mrr", label: "MRR", format: "money", hint: "Monthly recurring revenue at month end" },
  { key: "arr", label: "ARR", format: "money", hint: "MRR times twelve" },
  { key: "nrr", label: "Net revenue retention", format: "percent", hint: "Revenue kept from last month's clients, including upgrades" },
  { key: "arpa", label: "ARPA", format: "money", hint: "Average MRR per active account" },
  { key: "collections_rate", label: "Collections rate", format: "percent", hint: "Share of invoiced amount that has been paid" },
  { key: "receivables", label: "Outstanding receivables", format: "money", hint: "Issued and overdue invoices not yet paid" },
];

function Sparkline({ values, color }: { values: (number | null)[]; color: string }) {
  const points = values.map((v, i) => (v === null ? null : [i, v] as const)).filter((x): x is readonly [number, number] => x !== null);
  if (points.length < 2) return null;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const [minY, maxY] = [Math.min(...ys), Math.max(...ys)];
  const w = 96;
  const h = 28;
  const path = points.map(([x, y], i) => `${i ? "L" : "M"}${((x - xs[0]) / (xs[xs.length - 1] - xs[0] || 1)) * w},${h - 2 - ((y - minY) / (maxY - minY || 1)) * (h - 4)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true" className="overflow-visible">
      <path d={path} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function KpiRow({ q, asOf }: { q: Record<string, string | boolean>; asOf: string }) {
  const p = usePalette();
  const { data, isLoading, error } = useAnalytics<KpiSummary>("/revenue/summary", { ...q, as_of: asOf });
  if (error) return <p role="alert" className="text-risk-high">KPIs could not be loaded.</p>;
  return (
    <section aria-label="Key figures" className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
      {KPIS.map((k) => {
        const kpi = data?.kpis[k.key];
        const d = deltaText(kpi?.delta ?? null, kpi?.delta_pct ?? null);
        const good = k.key === "receivables" ? d.direction === "down" : d.direction === "up";
        const Icon = d.direction === "up" ? ArrowUp : d.direction === "down" ? ArrowDown : ArrowRight;
        return (
          <Card key={k.key}>
            <CardContent className="p-4">
              <p className="text-sm font-medium text-stone-700" title={k.hint}>{k.label}</p>
              {isLoading || !kpi ? <Skeleton className="mt-2 h-8 w-24" /> : (
                <>
                  <p className="mt-1 text-xl font-semibold tabular-nums text-navy" data-testid={`kpi-${k.key}`}>{formatKpi(kpi.value, k.format)}</p>
                  <p className={`mt-1 flex items-center gap-1 text-xs font-medium ${d.direction === "flat" ? "text-stone-700" : good ? "text-risk-low" : "text-risk-high"}`}>
                    <Icon className="h-3 w-3" aria-hidden="true" /> {d.text}
                  </p>
                  <div className="mt-2"><Sparkline values={kpi.sparkline} color={p.series[0]} /></div>
                </>
              )}
            </CardContent>
          </Card>
        );
      })}
    </section>
  );
}

export function RevenueTab({ filters, today }: TabProps) {
  const p = usePalette();
  const q = useMemo(() => filterQuery(filters, today), [filters, today]);
  const range = rangeOf(filters, today);
  const g = allowedGranularity(filters.granularity, range.from, range.to);
  const monthly = effectiveGranularity(g, true);
  const ts = (metric: string, gran = g, extra: Record<string, string> = {}) => useAnalytics<Rows<SeriesPoint>>("/revenue/timeseries", { ...q, metric, granularity: gran, ...extra });

  const total = ts("revenue", g, filters.compare ? { compare: "previous" } : {});
  const sub = ts("subscription_revenue");
  const addon = ts("addon_revenue");
  const over = ts("overage_revenue");
  const growth = ts("mrr_growth_rate", monthly);
  const growthMa = ts("mrr_growth_ma3", monthly);
  const byPlan = useAnalytics<Rows<BreakdownRow>>("/revenue/breakdown", { ...q, by: "plan" });
  const byIndustry = useAnalytics<Rows<BreakdownRow>>("/revenue/breakdown", { ...q, by: "industry" });
  const byClient = useAnalytics<Rows<BreakdownRow>>("/revenue/breakdown", { ...q, by: "client" });
  const walk = useAnalytics<Rows<WalkRowApi>>("/revenue/mrr-walk", q);
  const aging = useAnalytics<AgingResponse>("/revenue/aging", { ...q, as_of: range.to });
  const cohorts = useAnalytics<CohortResponse>("/revenue/cohorts", q);

  // ---- revenue combo ----
  const comboOption = useMemo(() => {
    if (!total.data || !sub.data || !addon.data || !over.data) return undefined;
    const labels = total.data.rows.map((r) => periodLabel(r.period, g));
    const val = (r?: SeriesPoint) => r?.value ?? 0;
    const trend = movingAverage(total.data.rows.map((r) => val(r)), 3);
    const money = { valueFormatter: (v: unknown) => fmtMoney(Number(v)) };
    const surface = p.surface;
    const stack = (name: string, rows: SeriesPoint[], colour: string, top = false) => ({
      name, type: "bar", stack: "revenue", barMaxWidth: 28, data: rows.map(val), color: colour, tooltip: money,
      itemStyle: { color: colour, borderColor: surface, borderWidth: 1, borderRadius: top ? [4, 4, 0, 0] : 0 },
    });
    const series: unknown[] = [
      stack("Subscription", sub.data.rows, p.series[0]),
      stack("Add-on seats", addon.data.rows, p.series[2]),
      stack("Overage", over.data.rows, p.series[1], true),
      { name: "3-period average", type: "line", data: trend, smooth: true, showSymbol: false, lineStyle: { width: 2, color: p.text }, itemStyle: { color: p.text }, tooltip: money },
    ];
    if (filters.compare) {
      series.push({ name: "Previous period", type: "line", data: total.data.rows.map((r) => r.previous ?? null), showSymbol: false, lineStyle: { width: 2, type: "dashed", color: p.reference }, itemStyle: { color: p.reference }, tooltip: money });
    }
    return {
      ...baseOption(p),
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "category", data: labels, ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "USD", ...axisStyle(p), axisLabel: { ...axisStyle(p).axisLabel, formatter: (v: number) => fmtCompactMoney(v) } },
      series,
    };
  }, [total.data, sub.data, addon.data, over.data, p, g, filters.compare]);

  const comboGap = total.data && sub.data && addon.data && over.data
    ? maxGap(total.data.rows.map((r) => r.value ?? 0), total.data.rows.map((_, i) => (sub.data!.rows[i]?.value ?? 0) + (addon.data!.rows[i]?.value ?? 0) + (over.data!.rows[i]?.value ?? 0)))
    : 0;

  // ---- waterfall ----
  const wf = useMemo(() => (walk.data ? waterfall(walk.data.rows) : null), [walk.data]);
  const wfOption = useMemo(() => {
    if (!wf) return undefined;
    const label = { show: true, position: "top", color: p.textSecondary, fontSize: 11, formatter: (x: { value: number }) => (x.value ? fmtCompactMoney(x.value) : "") };
    const bar = (name: string, data: number[], colour: string) => ({ name, type: "bar", stack: "w", data, barMaxWidth: 44, itemStyle: { color: colour, borderRadius: [4, 4, 0, 0] }, label, tooltip: { valueFormatter: (v: unknown) => (v ? fmtMoney(Number(v)) : "-") } });
    return {
      ...baseOption(p),
      legend: { show: false },
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "category", data: wf.labels, ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "USD per month", ...axisStyle(p), axisLabel: { ...axisStyle(p).axisLabel, formatter: (v: number) => fmtCompactMoney(v) } },
      series: [
        { name: "base", type: "bar", stack: "w", data: wf.base, itemStyle: { color: "transparent" }, tooltip: { show: false }, silent: true },
        bar("MRR", wf.total, p.series[0]),
        bar("Increase", wf.up, p.good),
        bar("Decrease", wf.down, p.critical),
      ],
    };
  }, [wf, p]);

  // ---- plan donut ----
  const donut = useMemo(() => {
    if (!byPlan.data) return undefined;
    return {
      ...baseOption(p),
      legend: { ...(baseOption(p).legend as object), top: undefined, bottom: 0 },
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "item", formatter: (x: { name: string; value: number; percent: number }) => `${x.name}<br/><b>${fmtMoney(x.value)}</b> (${x.percent}%)` },
      series: [{
        type: "pie", radius: ["52%", "78%"], center: ["50%", "46%"], avoidLabelOverlap: true, label: { show: false },
        itemStyle: { borderColor: p.surface, borderWidth: 2 },
        data: byPlan.data.rows.map((r) => ({ name: r.label, value: r.revenue, itemStyle: { color: p.series[PLAN_SLOT[r.key] ?? 3] } })),
      }],
    };
  }, [byPlan.data, p]);

  const industryOption = useMemo(() => {
    if (!byIndustry.data) return undefined;
    const rows = [...byIndustry.data.rows].sort((a, b) => a.revenue - b.revenue);
    return {
      ...baseOption(p),
      legend: { show: false },
      grid: { left: 8, right: 64, top: 8, bottom: 8, containLabel: true },
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v: unknown) => fmtMoney(Number(v)) },
      xAxis: { type: "value", name: "USD", ...axisStyle(p), axisLabel: { ...axisStyle(p).axisLabel, formatter: (v: number) => fmtCompactMoney(v) } },
      yAxis: { type: "category", data: rows.map((r) => r.label), ...axisStyle(p), splitLine: { show: false } },
      series: [{ name: "Revenue", type: "bar", barMaxWidth: 22, data: rows.map((r) => r.revenue), itemStyle: { color: p.series[0], borderRadius: [0, 4, 4, 0] }, label: { show: true, position: "right", color: p.textSecondary, formatter: (x: { value: number }) => fmtCompactMoney(x.value) } }],
    };
  }, [byIndustry.data, p]);

  // ---- aging ----
  const agingOption = useMemo(() => {
    if (!aging.data) return undefined;
    const colours = [p.good, p.warning, p.serious, p.critical];
    return {
      ...baseOption(p),
      grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "item", formatter: (x: { seriesName: string; value: number }) => `${x.seriesName}<br/><b>${fmtMoney(x.value)}</b>` },
      xAxis: { type: "value", name: "USD outstanding", ...axisStyle(p), axisLabel: { ...axisStyle(p).axisLabel, formatter: (v: number) => fmtCompactMoney(v) } },
      yAxis: { type: "category", data: ["Unpaid invoices"], ...axisStyle(p), splitLine: { show: false } },
      series: aging.data.rows.map((r, i) => ({
        name: bucketName(r.bucket), type: "bar", stack: "aging", barMaxWidth: 44, data: [r.amount],
        itemStyle: { color: colours[i % colours.length], borderColor: p.surface, borderWidth: 1 },
        label: { show: r.amount > 0, color: "#0b1f3a", formatter: () => fmtCompactMoney(r.amount) },
      })),
    };
  }, [aging.data, p]);

  // ---- cohort heatmap ----
  const cohort = useMemo(() => {
    if (!cohorts.data) return null;
    const grid = cohortCells(cohorts.data.matrix, 24);
    return {
      grid,
      option: {
        ...baseOption(p),
        legend: { show: false },
        grid: { left: 8, right: 16, top: 8, bottom: 44, containLabel: true },
        tooltip: { ...(baseOption(p).tooltip as object), trigger: "item", formatter: (x: { value: [number, number, number] }) => `Cohort ${grid.cohorts[x.value[1]].slice(0, 7)}<br/>Month ${x.value[0]}: <b>${x.value[2].toFixed(1)}%</b> still paying` },
        xAxis: { type: "category", data: grid.months, name: "Months since signup", nameLocation: "middle", nameGap: 26, ...axisStyle(p), splitLine: { show: false } },
        yAxis: { type: "category", data: grid.cohorts.map((c) => c.slice(0, 7)), inverse: true, name: "Signup month", ...axisStyle(p), splitLine: { show: false } },
        visualMap: { min: 0, max: 100, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120, text: ["100%", "0%"], textStyle: { color: p.textSecondary }, inRange: { color: p.ramp } },
        series: [{ type: "heatmap", data: grid.cells, itemStyle: { borderColor: p.surface, borderWidth: 1 } }],
      },
    };
  }, [cohorts.data, p]);

  // ---- growth ----
  const growthOption = useMemo(() => {
    if (!growth.data || !growthMa.data) return undefined;
    const labels = growth.data.rows.map((r) => periodLabel(r.period, "month"));
    return {
      ...baseOption(p),
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => (v === null || v === undefined ? "n/a" : fmtPct(Number(v), 2)) },
      xAxis: { type: "category", data: labels, ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "% month on month", ...axisStyle(p), axisLabel: { ...axisStyle(p).axisLabel, formatter: "{value}%" } },
      series: [
        { name: "Monthly growth", type: "line", data: growth.data.rows.map((r) => r.value), showSymbol: false, lineStyle: { width: 2, color: p.series[0] }, itemStyle: { color: p.series[0] } },
        { name: "3-month average", type: "line", data: growthMa.data.rows.map((r) => r.value), showSymbol: false, lineStyle: { width: 2, color: p.series[1] }, itemStyle: { color: p.series[1] } },
      ],
    };
  }, [growth.data, growthMa.data, p]);

  const topClients = useMemo(() => [...(byClient.data?.rows ?? [])].sort((a, b) => b.revenue - a.revenue).slice(0, 10), [byClient.data]);
  const comboQuery = { ...q, metric: "revenue", granularity: g };
  const tableOf = (rows?: SeriesPoint[]) => (rows ? { columns: ["Period", "Value"], rows: rows.map((r) => [r.period, r.value]) } : undefined);

  return (
    <div className="space-y-6">
      <KpiRow q={q} asOf={range.to} />

      <ChartCard
        title="Revenue by period"
        description="Invoiced revenue stacked by subscription, add-on seats and overage, with a three-period average."
        height={340}
        option={comboOption}
        loading={!comboOption && !total.error}
        error={total.error ?? sub.error ?? addon.error ?? over.error}
        empty={!!total.data && total.data.rows.every((r) => !r.value)}
        csv={{ path: "/revenue/timeseries", query: comboQuery, filename: csvName("revenue", filters, today) }}
        table={total.data && sub.data && addon.data && over.data ? { columns: ["Period", "Subscription", "Add-on seats", "Overage", "Total"], rows: total.data.rows.map((r, i) => [r.period, sub.data!.rows[i]?.value ?? 0, addon.data!.rows[i]?.value ?? 0, over.data!.rows[i]?.value ?? 0, r.value]) } : undefined}
        note={total.data ? `Subscription + add-on seats + overage equals the total (largest difference ${fmtMoney(comboGap, 2)}). Revenue is attributed by invoice ${g === "month" ? "period month" : "issue date"}.` : null}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="MRR movement"
          description="Opening MRR plus new and expansion, minus contraction and churn, equals closing MRR for the range."
          option={wfOption}
          loading={!wfOption && !walk.error}
          error={walk.error}
          empty={!!walk.data && walk.data.rows.length === 0}
          csv={{ path: "/revenue/mrr-walk", query: q, filename: csvName("mrr_walk", filters, today) }}
          table={wf ? { columns: ["Step", "USD"], rows: wf.steps.map((s) => [s.label, round2(s.value)]) } : undefined}
          note={wf ? (wf.reconciles ? "Opening plus movements equals closing MRR." : "Warning: movements do not add up to closing MRR.") : null}
        />
        <ChartCard
          title="Revenue growth"
          description="Month-on-month change in MRR with a three-month moving average."
          option={growthOption}
          loading={!growthOption && !growth.error}
          error={growth.error ?? growthMa.error}
          empty={!!growth.data && growth.data.rows.every((r) => r.value === null)}
          csv={{ path: "/revenue/timeseries", query: { ...q, metric: "mrr_growth_rate", granularity: "month" }, filename: csvName("mrr_growth", filters, today) }}
          table={tableOf(growth.data?.rows)}
          note={g !== "month" ? "Growth is only available per month." : null}
        />
        <ChartCard
          title="Revenue by plan"
          description="Share of revenue earned from each plan over the range."
          option={donut}
          loading={!donut && !byPlan.error}
          error={byPlan.error}
          empty={!!byPlan.data && byPlan.data.rows.length === 0}
          csv={{ path: "/revenue/breakdown", query: { ...q, by: "plan" }, filename: csvName("revenue_by_plan", filters, today) }}
          table={byPlan.data ? { columns: ["Plan", "Revenue", "Share", "Clients"], rows: byPlan.data.rows.map((r) => [r.label, r.revenue, `${r.share_pct}%`, r.clients]) } : undefined}
        />
        <ChartCard
          title="Revenue by client type"
          description="Revenue earned from each client industry over the range."
          option={industryOption}
          loading={!industryOption && !byIndustry.error}
          error={byIndustry.error}
          empty={!!byIndustry.data && byIndustry.data.rows.length === 0}
          csv={{ path: "/revenue/breakdown", query: { ...q, by: "industry" }, filename: csvName("revenue_by_industry", filters, today) }}
          table={byIndustry.data ? { columns: ["Industry", "Revenue", "Share", "Clients"], rows: byIndustry.data.rows.map((r) => [r.label, r.revenue, `${r.share_pct}%`, r.clients]) } : undefined}
        />
      </div>

      <Card>
        <CardContent className="p-5">
          <h2 className="text-base">Top 10 clients</h2>
          <p className="mt-0.5 text-sm text-stone-700">Ranked by revenue over the range, with reports generated and the change against the previous period.</p>
          {byClient.isLoading ? <Skeleton className="mt-3 h-48" /> : byClient.error ? <p role="alert" className="mt-3 text-risk-high">The client table could not be loaded.</p> : topClients.length === 0 ? <p className="mt-3 text-stone-700">No client revenue for these filters.</p> : (
            <Table className="mt-2">
              <caption className="sr-only">Top 10 clients by revenue</caption>
              <TableHead><TableRow><TableHeader scope="col">Client</TableHeader><TableHeader scope="col" className="text-right">Revenue</TableHeader><TableHeader scope="col" className="text-right">Share</TableHeader><TableHeader scope="col" className="text-right">Reports</TableHeader><TableHeader scope="col" className="text-right">Trend</TableHeader></TableRow></TableHead>
              <TableBody>
                {topClients.map((c) => {
                  const trend = c.trend_pct ?? null;
                  const Icon = trend === null || trend === 0 ? ArrowRight : trend > 0 ? ArrowUp : trend < 0 ? ArrowDown : ArrowRight;
                  return (
                    <TableRow key={c.key}>
                      <TableCell className="font-medium text-navy">{c.label}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtMoney(c.revenue)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtPct(c.share_pct)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtInt(c.reports ?? 0)}</TableCell>
                      <TableCell className="text-right tabular-nums"><span className="inline-flex items-center gap-1"><Icon className="h-3 w-3" aria-hidden="true" />{trend === null ? "n/a" : `${trend > 0 ? "+" : ""}${trend.toFixed(1)}%`}</span></TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Invoice aging"
          description={`Unpaid invoices by how long they have been outstanding at ${range.to}.`}
          height={170}
          option={agingOption}
          loading={!agingOption && !aging.error}
          error={aging.error}
          empty={!!aging.data && aging.data.rows.every((r) => !r.amount)}
          emptyText="Nothing is outstanding."
          csv={{ path: "/revenue/aging", query: { ...q, as_of: range.to }, filename: csvName("invoice_aging", filters, today) }}
          table={aging.data ? { columns: ["Bucket", "Invoices", "Amount"], rows: aging.data.rows.map((r) => [bucketName(r.bucket), r.invoices, r.amount]) } : undefined}
          note={aging.data ? `Outstanding ${fmtMoney(Number(aging.data.meta.outstanding ?? 0))}.` : null}
        />
        <Card>
          <CardContent className="p-5">
            <h2 className="text-base">Invoices by status</h2>
            <p className="mt-0.5 text-sm text-stone-700">Count and value of invoices in each state.</p>
            {aging.isLoading ? <Skeleton className="mt-3 h-32" /> : (
              <Table className="mt-2">
                <caption className="sr-only">Invoice status</caption>
                <TableHead><TableRow><TableHeader scope="col">Status</TableHeader><TableHeader scope="col" className="text-right">Invoices</TableHeader><TableHeader scope="col" className="text-right">Amount</TableHeader></TableRow></TableHead>
                <TableBody>
                  {(aging.data?.statuses ?? []).map((s) => (
                    <TableRow key={s.status}>
                      <TableCell><Badge tone={s.status === "paid" ? "low" : s.status === "overdue" ? "high" : s.status === "void" ? "neutral" : "medium"} className="capitalize">{s.status}</Badge></TableCell>
                      <TableCell className="text-right tabular-nums">{fmtInt(s.invoices)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtMoney(s.amount)}</TableCell>
                    </TableRow>
                  ))}
                  <TableRow><TableHeader scope="row">Total</TableHeader><TableCell className="text-right font-semibold tabular-nums">{fmtInt(sum((aging.data?.statuses ?? []).map((s) => s.invoices)))}</TableCell><TableCell className="text-right font-semibold tabular-nums">{fmtMoney(sum((aging.data?.statuses ?? []).map((s) => s.amount)))}</TableCell></TableRow>
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      <ChartCard
        title="Cohort retention"
        description="Share of each signup month's clients still paying after N months."
        height={Math.max(260, (cohort?.grid.cohorts.length ?? 12) * 20 + 80)}
        option={cohort?.option}
        loading={!cohort && !cohorts.error}
        error={cohorts.error}
        empty={!!cohort && cohort.grid.cells.length === 0}
        csv={{ path: "/revenue/cohorts", query: q, filename: csvName("cohort_retention", filters, today) }}
        table={cohorts.data ? { columns: ["Cohort", "Clients", "Month 0", "Month 3", "Month 6", "Month 12"], rows: cohorts.data.matrix.map((m) => [m.cohort.slice(0, 7), m.size, ...[0, 3, 6, 12].map((k) => m.retention[String(k)] ?? null)]) } : undefined}
      />
    </div>
  );
}

const BUCKET_NAMES: Record<string, string> = { current: "Current", "1-30": "1 to 30 days", "31-60": "31 to 60 days", "60+": "60+ days" };
export const bucketName = (b: string) => BUCKET_NAMES[b] ?? b.replace(/_/g, " ");
