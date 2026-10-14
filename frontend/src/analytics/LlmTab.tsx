import { useMemo } from "react";

import { ChartCard } from "@/analytics/ChartCard";
import { axisStyle, baseOption, usePalette } from "@/analytics/chartkit";
import { useAnalytics, type CostRow, type EfficiencyResponse, type MarginRow, type Rows } from "@/analytics/data";
import { allowedGranularity, csvName, filterQuery, fmtCompactInt, fmtInt, fmtMoney, fmtPct, periodLabel, pivotTokens, rangeOf, type Granularity } from "@/analytics/logic";
import type { TabProps } from "@/analytics/RevenueTab";
import { PROVIDER_SLOT } from "@/analytics/theme";
import { Card, CardContent, Skeleton } from "@/components/ui/card";

const PROVIDER_LABEL: Record<string, string> = { groq: "Groq", gemini: "Gemini", cache: "Cache", local: "Local" };

function Quota({ name, used, limit, percent }: { name: string; used: number; limit: number; percent: number }) {
  const pct = Math.min(100, percent);
  return (
    <div>
      <div className="flex justify-between text-sm"><span className="font-medium capitalize">{name}</span><span className="font-mono tabular-nums">{fmtInt(used)} / {fmtInt(limit)} tokens</span></div>
      <div className="mt-1 h-3 rounded-full bg-stone-200" role="meter" aria-label={`${name} daily token quota used`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <div className={`h-3 rounded-full ${pct > 85 ? "bg-risk-high" : pct > 60 ? "bg-risk-medium" : "bg-teal-600"}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-xs text-stone-700">{fmtPct(percent)} of today's allowance used{pct > 85 ? ". Close to the limit; the gateway will fall back to the other provider." : ""}</p>
    </div>
  );
}

export function LlmTab({ filters, today }: TabProps) {
  const p = usePalette();
  const q = useMemo(() => filterQuery(filters, today), [filters, today]);
  const range = rangeOf(filters, today);
  const g: Granularity = allowedGranularity(filters.granularity, range.from, range.to);

  const tokens = useAnalytics<Rows<{ period: string; provider: string; tokens: number }>>("/llm/tokens", { ...q, granularity: g });
  const eff = useAnalytics<EfficiencyResponse>("/llm/efficiency", q);
  const cost = useAnalytics<Rows<CostRow>>("/llm/cost", q);
  const margin = useAnalytics<Rows<MarginRow>>("/revenue/margin", q);

  const pivot = useMemo(() => (tokens.data ? pivotTokens(tokens.data.rows) : null), [tokens.data]);
  const tokenOption = useMemo(() => {
    if (!pivot) return undefined;
    return {
      ...baseOption(p),
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => `${fmtInt(Number(v))} tokens` },
      xAxis: { type: "category", data: pivot.periods.map((d) => periodLabel(d, g)), boundaryGap: false, ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "Tokens", ...axisStyle(p), axisLabel: { ...axisStyle(p).axisLabel, formatter: (v: number) => fmtCompactInt(v) } },
      series: pivot.series.map((s) => {
        const colour = p.series[PROVIDER_SLOT[s.provider] ?? 4];
        return { name: PROVIDER_LABEL[s.provider] ?? s.provider, type: "line", stack: "tokens", data: s.values, showSymbol: false, areaStyle: { color: colour, opacity: 0.55 }, lineStyle: { width: 2, color: colour }, itemStyle: { color: colour } };
      }),
    };
  }, [pivot, p, g]);

  const rateOption = useMemo(() => {
    if (!eff.data) return undefined;
    const rows = eff.data.rows;
    const line = (name: string, key: "cache_hit_rate" | "fallback_rate", colour: string) => ({ name, type: "line", data: rows.map((r) => r[key]), showSymbol: false, lineStyle: { width: 2, color: colour }, itemStyle: { color: colour } });
    return {
      ...baseOption(p),
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => fmtPct(Number(v)) },
      xAxis: { type: "category", data: rows.map((r) => periodLabel(r.month, "month")), ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "% of calls", min: 0, ...axisStyle(p), axisLabel: { ...axisStyle(p).axisLabel, formatter: "{value}%" } },
      series: [line("Cache hit rate", "cache_hit_rate", p.series[2]), line("Fallback rate", "fallback_rate", p.series[1])],
    };
  }, [eff.data, p]);

  const perCaseOption = useMemo(() => {
    if (!eff.data) return undefined;
    const rows = eff.data.rows;
    const target = Number(eff.data.meta.target_tokens_per_case ?? rows[0]?.target ?? 9000);
    return {
      ...baseOption(p),
      legend: { show: false },
      tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => `${fmtInt(Number(v))} tokens` },
      xAxis: { type: "category", data: rows.map((r) => periodLabel(r.month, "month")), ...axisStyle(p), splitLine: { show: false } },
      yAxis: { type: "value", name: "Tokens per case", min: 0, ...axisStyle(p), axisLabel: { ...axisStyle(p).axisLabel, formatter: (v: number) => fmtCompactInt(v) } },
      series: [{
        name: "Tokens per case", type: "line", data: rows.map((r) => r.tokens_per_case), showSymbol: false, lineStyle: { width: 2, color: p.series[0] }, itemStyle: { color: p.series[0] },
        markLine: { silent: true, symbol: "none", lineStyle: { color: p.reference, type: "dashed", width: 1.5 }, label: { formatter: `Target ${fmtInt(target)}`, color: p.textSecondary, position: "insideEndTop" }, data: [{ yAxis: target }] },
      }],
    };
  }, [eff.data, p]);

  const small = (rows: { label: string; value: number | null }[], name: string, formatter: (v: number) => string, axisName: string, colour: string) => ({
    ...baseOption(p),
    legend: { show: false },
    grid: { left: 8, right: 12, top: 28, bottom: 8, containLabel: true },
    tooltip: { ...(baseOption(p).tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => formatter(Number(v)) },
    xAxis: { type: "category", data: rows.map((r) => r.label), ...axisStyle(p), splitLine: { show: false } },
    yAxis: { type: "value", name: axisName, ...axisStyle(p), axisLabel: { ...axisStyle(p).axisLabel, formatter: (v: number) => formatter(v) } },
    series: [{ name, type: "line", data: rows.map((r) => r.value), showSymbol: false, lineStyle: { width: 2, color: colour }, itemStyle: { color: colour } }],
  });

  const revPerCase = useMemo(() => (cost.data ? small(cost.data.rows.map((r) => ({ label: periodLabel(r.month, "month"), value: r.revenue_per_case })), "Revenue per case", (v) => fmtMoney(v), "USD", p.series[0]) : undefined), [cost.data, p]); // eslint-disable-line react-hooks/exhaustive-deps
  const costPerCase = useMemo(() => (cost.data ? small(cost.data.rows.map((r) => ({ label: periodLabel(r.month, "month"), value: r.cost_per_case })), "Model cost per case", (v) => fmtMoney(v, 4), "USD", p.series[1]) : undefined), [cost.data, p]); // eslint-disable-line react-hooks/exhaustive-deps
  const marginOption = useMemo(() => (margin.data ? small(margin.data.rows.map((r) => ({ label: periodLabel(r.month, "month"), value: r.gross_margin_pct })), "Gross margin", (v) => fmtPct(v), "% of revenue", p.series[2]) : undefined), [margin.data, p]); // eslint-disable-line react-hooks/exhaustive-deps

  const csv = (path: string, name: string, extra: Record<string, string | number> = {}) => ({ path, query: { ...q, ...extra }, filename: csvName(name, filters, today) });
  const quota = eff.data?.quota ?? [];
  const lastMargin = margin.data?.rows.at(-1);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="p-5">
          <h2 className="text-base">Quota used today</h2>
          <p className="mt-0.5 text-sm text-stone-700">Daily token allowance of each provider, from the gateway's own counters.</p>
          {eff.isLoading ? <Skeleton className="mt-3 h-16" /> : quota.length === 0 ? <p className="mt-3 text-stone-700">No provider is configured, so analysis runs in local mode.</p> : (
            <div className="mt-3 grid gap-6 md:grid-cols-2">{quota.map((x) => <Quota key={x.name} name={x.name} used={x.day.tokens_used} limit={x.day.tokens_limit} percent={x.day.tokens_percent} />)}</div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Tokens by provider" description="Tokens spent per period, stacked by provider." option={tokenOption} loading={!tokenOption && !tokens.error} error={tokens.error} empty={!!tokens.data && tokens.data.rows.length === 0} csv={csv("/llm/tokens", "llm_tokens", { granularity: g })} table={pivot ? { columns: ["Period", ...pivot.providers.map((x) => PROVIDER_LABEL[x] ?? x)], rows: pivot.periods.map((d, i) => [d, ...pivot.series.map((s) => s.values[i])]) } : undefined} />
        <ChartCard title="Tokens per case" description="Average tokens spent on each case, against the target." option={perCaseOption} loading={!perCaseOption && !eff.error} error={eff.error} empty={!!eff.data && eff.data.rows.length === 0} csv={csv("/llm/efficiency", "llm_efficiency")} table={eff.data ? { columns: ["Month", "Cases", "Tokens", "Tokens per case", "Target"], rows: eff.data.rows.map((r) => [r.month, r.cases, r.tokens, r.tokens_per_case, r.target]) } : undefined} />
        <ChartCard title="Cache hits and fallbacks" description="Share of calls answered from the cache, and share that had to use the second provider or local mode." option={rateOption} loading={!rateOption && !eff.error} error={eff.error} empty={!!eff.data && eff.data.rows.length === 0} csv={csv("/llm/efficiency", "llm_efficiency")} table={eff.data ? { columns: ["Month", "Calls", "Cache hit %", "Fallback %"], rows: eff.data.rows.map((r) => [r.month, r.calls, r.cache_hit_rate, r.fallback_rate]) } : undefined} />
        <Card>
          <CardContent className="p-5">
            <h2 className="text-base">Unit economics, latest month</h2>
            <p className="mt-0.5 text-sm text-stone-700">Model cost is estimated at paid list prices for reference. The free tiers actually used cost nothing.</p>
            {margin.isLoading || cost.isLoading ? <Skeleton className="mt-3 h-24" /> : (
              <dl className="mt-3 grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-stone-50 p-3"><dt className="text-xs font-semibold uppercase text-stone-600">Revenue</dt><dd className="text-lg font-semibold tabular-nums text-navy">{fmtMoney(lastMargin?.revenue ?? null)}</dd></div>
                <div className="rounded-lg bg-stone-50 p-3"><dt className="text-xs font-semibold uppercase text-stone-600">Gross margin</dt><dd className="text-lg font-semibold tabular-nums text-navy">{fmtPct(lastMargin?.gross_margin_pct)}</dd></div>
                <div className="rounded-lg bg-stone-50 p-3"><dt className="text-xs font-semibold uppercase text-stone-600">Model cost</dt><dd className="text-lg font-semibold tabular-nums text-navy">{fmtMoney(lastMargin?.token_cost ?? null, 2)}</dd></div>
                <div className="rounded-lg bg-stone-50 p-3"><dt className="text-xs font-semibold uppercase text-stone-600">Infrastructure</dt><dd className="text-lg font-semibold tabular-nums text-navy">{fmtMoney(lastMargin?.infra_cost ?? null)}</dd></div>
              </dl>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <ChartCard title="Revenue per case" description="Invoiced revenue divided by cases handled." height={240} option={revPerCase} loading={!revPerCase && !cost.error} error={cost.error} empty={!!cost.data && cost.data.rows.length === 0} csv={csv("/llm/cost", "revenue_per_case")} table={cost.data ? { columns: ["Month", "Revenue", "Cases", "Revenue per case"], rows: cost.data.rows.map((r) => [r.month, r.revenue, r.cases, r.revenue_per_case]) } : undefined} />
        <ChartCard title="Model cost per case" description="Estimated model spend per case at list prices." height={240} option={costPerCase} loading={!costPerCase && !cost.error} error={cost.error} empty={!!cost.data && cost.data.rows.length === 0} csv={csv("/llm/cost", "cost_per_case")} table={cost.data ? { columns: ["Month", "Cost", "Cases", "Cost per case"], rows: cost.data.rows.map((r) => [r.month, r.cost, r.cases, r.cost_per_case]) } : undefined} />
        <ChartCard title="Gross margin" description="Revenue less model cost and infrastructure, as a share of revenue." height={240} option={marginOption} loading={!marginOption && !margin.error} error={margin.error} empty={!!margin.data && margin.data.rows.length === 0} csv={csv("/revenue/margin", "gross_margin")} table={margin.data ? { columns: ["Month", "Revenue", "Model cost", "Infrastructure", "Margin %"], rows: margin.data.rows.map((r) => [r.month, r.revenue, r.token_cost, r.infra_cost, r.gross_margin_pct]) } : undefined} note={typeof margin.data?.meta.basis === "string" ? margin.data.meta.basis : null} />
      </div>
    </div>
  );
}
