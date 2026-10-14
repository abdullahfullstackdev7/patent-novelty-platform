import { useMemo } from "react";

import { ChartCard } from "@/analytics/ChartCard";
import { axisStyle, baseOption, usePalette } from "@/analytics/chartkit";
import { useAnalytics, type AttorneyRow, type CpcResponse, type Rows, type SeriesPoint, type TurnaroundResponse } from "@/analytics/data";
import { allowedGranularity, csvName, filterQuery, fmtHours, fmtInt, fmtMs, heatGrid, periodLabel, rangeOf } from "@/analytics/logic";
import type { TabProps } from "@/analytics/RevenueTab";
import { RISK_LABEL, RISK_LEVELS, riskColor } from "@/analytics/theme";
import { Card, CardContent, Skeleton } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const STAGE_LABEL: Record<string, string> = { intake: "Intake", searched: "Searched", charted: "Charted", reviewed: "Reviewed", approved: "Approved" };
const monthLabel = (m: string) => periodLabel(m, "month");

export function OpsTab({ filters, today }: TabProps) {
  const p = usePalette();
  const q = useMemo(() => filterQuery(filters, today), [filters, today]);
  const range = rangeOf(filters, today);
  const g = allowedGranularity(filters.granularity, range.from, range.to);

  const reports = useAnalytics<Rows<SeriesPoint>>("/revenue/timeseries", { ...q, metric: "reports_generated", granularity: g });
  const funnel = useAnalytics<Rows<{ stage: string; cases: number }>>("/ops/funnel", q);
  const risk = useAnalytics<Rows<Record<string, number | string>>>("/ops/risk", q);
  const cpc = useAnalytics<CpcResponse>("/ops/cpc", { ...q, limit: 12 });
  const turn = useAnalytics<TurnaroundResponse>("/ops/turnaround", q);
  const backlog = useAnalytics<Rows<{ age: string; status: string; cases: number }>>("/ops/backlog", q);
  const attorneys = useAnalytics<Rows<AttorneyRow>>("/ops/attorneys", q);
  const latency = useAnalytics<Rows<{ month: string; searches: number; p50_ms: number; p95_ms: number }>>("/ops/latency", q);

  const line = (name: string, data: unknown[], colour: string, extra: Record<string, unknown> = {}) => ({
    name, type: "line", data, showSymbol: false, lineStyle: { width: 2, color: colour }, itemStyle: { color: colour }, ...extra,
  });

  const reportsOption = useMemo(() => {
    if (!reports.data) return undefined;
    return {
      ...baseOption(p),
      legend: { show: false },
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => `${fmtInt(Number(v))} reports` },
      xAxis: { type: "category", data: reports.data.rows.map((r) => periodLabel(r.period, g)), boundaryGap: false, ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "Reports", ...axisStyle(p) },
      series: [line("Reports generated", reports.data.rows.map((r) => r.value), p.series[0], { areaStyle: { color: p.series[0], opacity: 0.2 } })],
    };
  }, [reports.data, p, g]);

  const funnelOption = useMemo(() => {
    if (!funnel.data) return undefined;
    const ramp = p.ramp.slice(1); // ordinal ramp starts at step 250 so the first bar stays visible
    const rows = funnel.data.rows;
    return {
      ...baseOption(p),
      legend: { show: false },
      grid: { left: 8, right: 70, top: 8, bottom: 8, containLabel: true },
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v: unknown) => `${fmtInt(Number(v))} cases` },
      xAxis: { type: "value", name: "Cases", ...axisStyle(p) },
      yAxis: { type: "category", inverse: true, data: rows.map((r) => STAGE_LABEL[r.stage] ?? r.stage), ...axisStyle(p), splitLine: { show: false } },
      series: [{ name: "Cases", type: "bar", barMaxWidth: 30, data: rows.map((r, i) => ({ value: r.cases, itemStyle: { color: ramp[Math.min(i, ramp.length - 1)], borderRadius: [0, 4, 4, 0] } })), label: { show: true, position: "right", color: p.textSecondary, formatter: (x: { value: number }) => fmtInt(x.value) } }],
    };
  }, [funnel.data, p]);

  const riskOption = useMemo(() => {
    if (!risk.data) return undefined;
    return {
      ...baseOption(p),
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v: unknown) => `${fmtInt(Number(v))} cases` },
      xAxis: { type: "category", data: risk.data.rows.map((r) => monthLabel(String(r.month))), ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "Cases", ...axisStyle(p) },
      series: RISK_LEVELS.map((lvl, i) => ({
        name: RISK_LABEL[lvl], type: "bar", stack: "risk", barMaxWidth: 26, data: risk.data!.rows.map((r) => r[lvl]),
        itemStyle: { color: riskColor(p, lvl), borderColor: p.surface, borderWidth: 1, borderRadius: i === RISK_LEVELS.length - 1 ? [4, 4, 0, 0] : 0 },
      })),
    };
  }, [risk.data, p]);

  const cpcGrid = useMemo(() => (cpc.data ? heatGrid(cpc.data.heatmap) : null), [cpc.data]);
  const cpcOption = useMemo(() => {
    if (!cpcGrid) return undefined;
    return {
      ...baseOption(p),
      legend: { show: false },
      grid: { left: 8, right: 16, top: 8, bottom: 52, containLabel: true },
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "item", formatter: (x: { value: [number, number, number] }) => `${cpcGrid.subclasses[x.value[1]]}, ${monthLabel(cpcGrid.months[x.value[0]])}<br/><b>${fmtInt(x.value[2])}</b> votes` },
      xAxis: { type: "category", data: cpcGrid.months.map(monthLabel), ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "category", data: cpcGrid.subclasses, name: "CPC subclass", ...axisStyle(p), splitLine: { show: false } },
      visualMap: { min: 0, max: cpcGrid.max, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120, calculable: false, text: [fmtInt(cpcGrid.max), "0"], textStyle: { color: p.textSecondary }, inRange: { color: p.ramp } },
      series: [{ type: "heatmap", data: cpcGrid.cells, itemStyle: { borderColor: p.surface, borderWidth: 1 } }],
    };
  }, [cpcGrid, p]);

  const histOption = useMemo(() => {
    if (!turn.data) return undefined;
    return {
      ...baseOption(p),
      legend: { show: false },
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v: unknown) => `${fmtInt(Number(v))} cases` },
      xAxis: { type: "category", data: turn.data.rows.map((r) => r.bucket), name: "Hours from intake to approval", nameLocation: "middle", nameGap: 28, ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "Cases", ...axisStyle(p) },
      grid: { left: 8, right: 16, top: 24, bottom: 28, containLabel: true },
      series: [{ name: "Cases", type: "bar", barCategoryGap: "12%", data: turn.data.rows.map((r) => r.cases), itemStyle: { color: p.series[0], borderRadius: [4, 4, 0, 0] } }],
    };
  }, [turn.data, p]);

  const turnTrend = useMemo(() => {
    if (!turn.data) return undefined;
    const t = turn.data.trend;
    return {
      ...baseOption(p),
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => fmtHours(Number(v)) },
      xAxis: { type: "category", data: t.map((r) => monthLabel(r.month)), ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "Hours", ...axisStyle(p) },
      series: [line("Median (p50)", t.map((r) => r.p50_hours), p.series[0]), line("Slowest 10% (p90)", t.map((r) => r.p90_hours), p.series[1])],
    };
  }, [turn.data, p]);

  const latencyOption = useMemo(() => {
    if (!latency.data) return undefined;
    const t = latency.data.rows;
    return {
      ...baseOption(p),
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => fmtMs(Number(v)) },
      xAxis: { type: "category", data: t.map((r) => monthLabel(r.month)), ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "Milliseconds", ...axisStyle(p) },
      series: [line("Median (p50)", t.map((r) => r.p50_ms), p.series[0]), line("95th percentile (p95)", t.map((r) => r.p95_ms), p.series[1])],
    };
  }, [latency.data, p]);

  const csv = (path: string, name: string, extra: Record<string, string | number> = {}) => ({ path, query: { ...q, ...extra }, filename: csvName(name, filters, today) });
  const summary = turn.data?.summary;

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Reports generated" description="Reports produced per period, one per case." option={reportsOption} loading={!reportsOption && !reports.error} error={reports.error} empty={!!reports.data && reports.data.rows.every((r) => !r.value)} csv={csv("/revenue/timeseries", "reports_generated", { metric: "reports_generated", granularity: g })} table={reports.data ? { columns: ["Period", "Reports"], rows: reports.data.rows.map((r) => [r.period, r.value]) } : undefined} />
        <ChartCard title="Case funnel" description="How many cases reach each stage, from intake to approval." option={funnelOption} loading={!funnelOption && !funnel.error} error={funnel.error} empty={!!funnel.data && funnel.data.rows[0]?.cases === 0} csv={csv("/ops/funnel", "case_funnel")} table={funnel.data ? { columns: ["Stage", "Cases"], rows: funnel.data.rows.map((r) => [STAGE_LABEL[r.stage] ?? r.stage, r.cases]) } : undefined} />
        <ChartCard title="Risk distribution" description="Cases created each month by assessed risk level." option={riskOption} loading={!riskOption && !risk.error} error={risk.error} empty={!!risk.data && risk.data.rows.every((r) => RISK_LEVELS.every((l) => !r[l]))} csv={csv("/ops/risk", "risk_distribution")} table={risk.data ? { columns: ["Month", ...RISK_LEVELS.map((l) => RISK_LABEL[l])], rows: risk.data.rows.map((r) => [String(r.month), ...RISK_LEVELS.map((l) => Number(r[l]))]) } : undefined} />
        <ChartCard title="Technology areas" description="CPC subclasses the searches voted for, by month." height={Math.max(280, (cpcGrid?.subclasses.length ?? 8) * 28 + 80)} option={cpcOption} loading={!cpcOption && !cpc.error} error={cpc.error} empty={!!cpcGrid && cpcGrid.cells.length === 0} csv={csv("/ops/cpc", "technology_areas", { limit: 12 })} table={cpc.data ? { columns: ["Subclass", "Votes", "Searches"], rows: cpc.data.rows.map((r) => [r.subclass, r.votes, r.searches]) } : undefined} />
        <ChartCard title="Turnaround time" description="Hours from intake to approval for approved cases." option={histOption} loading={!histOption && !turn.error} error={turn.error} empty={!!summary && summary.cases === 0} csv={csv("/ops/turnaround", "turnaround")} table={turn.data ? { columns: ["Bucket", "Cases"], rows: turn.data.rows.map((r) => [r.bucket, r.cases]) } : undefined} note={summary ? `${fmtInt(summary.cases)} approved cases. Median ${fmtHours(summary.p50_hours)}, slowest 10% ${fmtHours(summary.p90_hours)}.` : null} />
        <ChartCard title="Turnaround trend" description="Median and 90th percentile turnaround by approval month." option={turnTrend} loading={!turnTrend && !turn.error} error={turn.error} empty={!!turn.data && turn.data.trend.length === 0} csv={csv("/ops/turnaround", "turnaround_trend")} table={turn.data ? { columns: ["Month", "Cases", "p50 hours", "p90 hours"], rows: turn.data.trend.map((r) => [r.month, r.cases, r.p50_hours, r.p90_hours]) } : undefined} />
      </div>

      <ChartCard title="Search latency" description="Median and 95th percentile time to answer a search." option={latencyOption} loading={!latencyOption && !latency.error} error={latency.error} empty={!!latency.data && latency.data.rows.length === 0} csv={csv("/ops/latency", "search_latency")} table={latency.data ? { columns: ["Month", "Searches", "p50 ms", "p95 ms"], rows: latency.data.rows.map((r) => [r.month, r.searches, r.p50_ms, r.p95_ms]) } : undefined} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardContent className="p-5">
            <h2 className="text-base">Review backlog</h2>
            <p className="mt-0.5 text-sm text-stone-700">Cases waiting for a reviewer or for the author to act, by how long they have waited.</p>
            {backlog.isLoading ? <Skeleton className="mt-3 h-24" /> : backlog.error ? <p role="alert" className="mt-3 text-risk-high">The backlog could not be loaded.</p> : (backlog.data?.rows ?? []).length === 0 ? <p className="mt-3 text-stone-700">Nothing is waiting for review.</p> : (
              <Table className="mt-2">
                <caption className="sr-only">Review backlog</caption>
                <TableHead><TableRow><TableHeader scope="col">Waiting</TableHeader><TableHeader scope="col">Status</TableHeader><TableHeader scope="col" className="text-right">Cases</TableHeader></TableRow></TableHead>
                <TableBody>{backlog.data!.rows.map((r) => <TableRow key={`${r.age}${r.status}`}><TableCell>{r.age}</TableCell><TableCell className="capitalize">{r.status.replace("_", " ")}</TableCell><TableCell className="text-right tabular-nums">{fmtInt(r.cases)}</TableCell></TableRow>)}</TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <h2 className="text-base">Attorney throughput</h2>
            <p className="mt-0.5 text-sm text-stone-700">Cases owned and approved by each person over the range (top 10 by cases).</p>
            {attorneys.isLoading ? <Skeleton className="mt-3 h-24" /> : attorneys.error ? <p role="alert" className="mt-3 text-risk-high">Throughput could not be loaded.</p> : (attorneys.data?.rows ?? []).length === 0 ? <p className="mt-3 text-stone-700">No cases in this range.</p> : (
              <Table className="mt-2">
                <caption className="sr-only">Attorney throughput</caption>
                <TableHead><TableRow><TableHeader scope="col">Name</TableHeader><TableHeader scope="col" className="text-right">Cases</TableHeader><TableHeader scope="col" className="text-right">Approved</TableHeader><TableHeader scope="col" className="text-right">In review</TableHeader></TableRow></TableHead>
                <TableBody>{[...attorneys.data!.rows].sort((a, b) => b.cases - a.cases).slice(0, 10).map((r) => <TableRow key={r.user_id}><TableCell>{r.name}</TableCell><TableCell className="text-right tabular-nums">{fmtInt(r.cases)}</TableCell><TableCell className="text-right tabular-nums">{fmtInt(r.approved)}</TableCell><TableCell className="text-right tabular-nums">{fmtInt(r.in_review)}</TableCell></TableRow>)}</TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
