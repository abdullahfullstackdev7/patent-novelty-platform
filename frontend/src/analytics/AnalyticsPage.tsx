import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { useAnalytics, type KpiSummary } from "@/analytics/data";
import { FilterBar, useFilters } from "@/analytics/FilterBar";
import { LlmTab } from "@/analytics/LlmTab";
import { demoNote, filterQuery, rangeOf } from "@/analytics/logic";
import { OpsTab } from "@/analytics/OpsTab";
import { RevenueTab } from "@/analytics/RevenueTab";
import { PageHeader } from "@/app/components/Shell";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Seo } from "@/lib/seo";

const TABS = [
  { id: "revenue", label: "Revenue" },
  { id: "ops", label: "Usage and operations" },
  { id: "llm", label: "LLM and cost efficiency" },
] as const;

export default function AnalyticsPage({ today = new Date() }: { today?: Date }) {
  const [filters, update] = useFilters();
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab")! : "revenue";
  const stableToday = useMemo(() => today, [today.toDateString()]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useMemo(() => filterQuery(filters, stableToday), [filters, stableToday]);
  const range = rangeOf(filters, stableToday);
  // Same request as the KPI row, so it is served from the cache. Its meta carries the demo data note.
  const summary = useAnalytics<KpiSummary>("/revenue/summary", { ...q, as_of: range.to });
  const note = demoNote(summary.data?.meta);

  return (
    <>
      <Seo title="Analytics" description="Revenue, usage and language model efficiency." path="/app/analytics" />
      <PageHeader
        crumbs={[{ label: "Dashboard", to: "/app" }, { label: "Analytics" }]}
        title="Analytics"
        subtitle={
          <span>
            {range.from} to {range.to}
            {note && <span className="ml-3 rounded-full bg-teal-50 px-2.5 py-0.5 text-sm text-teal-800">{note}</span>}
          </span>
        }
      />
      <FilterBar filters={filters} onChange={update} today={stableToday} />
      <Tabs value={tab} onValueChange={(v) => setParams((old) => { const p = new URLSearchParams(old); p.set("tab", v); return p; }, { replace: true })}>
        <TabsList aria-label="Analytics sections">
          {TABS.map((t) => <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>)}
        </TabsList>
        <TabsContent value="revenue"><RevenueTab filters={filters} today={stableToday} /></TabsContent>
        <TabsContent value="ops"><OpsTab filters={filters} today={stableToday} /></TabsContent>
        <TabsContent value="llm"><LlmTab filters={filters} today={stableToday} /></TabsContent>
      </Tabs>
    </>
  );
}
