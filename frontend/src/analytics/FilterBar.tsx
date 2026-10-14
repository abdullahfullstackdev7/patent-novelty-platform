import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import {
  DEFAULT_FILTERS,
  PRESET_LABEL,
  allowedGranularity,
  rangeOf,
  type AnalyticsFilters,
  type Granularity,
  type Preset,
} from "@/analytics/logic";
import { api } from "@/app/client";
import { Button } from "@/components/ui/button";

const PRESETS = Object.keys(PRESET_LABEL) as Preset[];
const GRANULARITIES: Granularity[] = ["day", "week", "month"];

/** Filters live in the URL, so a dashboard view can be bookmarked or shared. */
export function useFilters(): [AnalyticsFilters, (patch: Partial<AnalyticsFilters>) => void] {
  const [params, setParams] = useSearchParams();
  const filters = useMemo<AnalyticsFilters>(() => {
    const preset = (params.get("range") as Preset) || DEFAULT_FILTERS.preset;
    const granularity = (params.get("by") as Granularity) || DEFAULT_FILTERS.granularity;
    return {
      preset: PRESETS.includes(preset) ? preset : DEFAULT_FILTERS.preset,
      from: params.get("from") ?? "",
      to: params.get("to") ?? "",
      granularity: GRANULARITIES.includes(granularity) ? granularity : DEFAULT_FILTERS.granularity,
      compare: params.get("compare") === "1",
      client: params.get("client") ?? "",
      plan: params.get("plan") ?? "",
      demo: params.get("demo") !== "0",
    };
  }, [params]);

  const update = useCallback(
    (patch: Partial<AnalyticsFilters>) => {
      const next = { ...filters, ...patch };
      setParams(
        (old) => {
          const p = new URLSearchParams(old);
          const set = (k: string, v: string | null) => (v ? p.set(k, v) : p.delete(k));
          set("range", next.preset === DEFAULT_FILTERS.preset ? null : next.preset);
          set("from", next.preset === "custom" ? next.from : null);
          set("to", next.preset === "custom" ? next.to : null);
          set("by", next.granularity === "month" ? null : next.granularity);
          set("compare", next.compare ? "1" : null);
          set("client", next.client);
          set("plan", next.plan);
          set("demo", next.demo ? null : "0");
          return p;
        },
        { replace: true },
      );
    },
    [filters, setParams],
  );
  return [filters, update];
}

const select = "h-10 rounded-lg border border-stone-300 bg-white px-2 text-sm text-navy";

export function FilterBar({ filters, onChange, today }: { filters: AnalyticsFilters; onChange: (p: Partial<AnalyticsFilters>) => void; today: Date }) {
  const clients = useQuery({ queryKey: ["billing-clients-list"], queryFn: () => api<{ items: { id: string; name: string }[] }>("/billing/clients", { query: { include_demo: true, limit: 200 } }), staleTime: 300_000 });
  const plans = useQuery({ queryKey: ["billing-plans-list"], queryFn: () => api<{ code: string; name: string }[]>("/billing/plans"), staleTime: 300_000 });
  const range = rangeOf(filters, today);
  const effective = allowedGranularity(filters.granularity, range.from, range.to);

  return (
    <form aria-label="Dashboard filters" className="sticky top-16 z-20 -mx-4 mb-6 flex flex-wrap items-end gap-3 border-b border-stone-200 bg-white/95 px-4 py-3 backdrop-blur md:-mx-8 md:px-8" onSubmit={(e) => e.preventDefault()}>
      <div>
        <label htmlFor="flt-range" className="mb-1 block text-xs font-semibold">Date range</label>
        <select id="flt-range" className={select} value={filters.preset} onChange={(e) => onChange({ preset: e.target.value as Preset, from: range.from, to: range.to })}>
          {PRESETS.map((p) => <option key={p} value={p}>{PRESET_LABEL[p]}</option>)}
        </select>
      </div>
      {filters.preset === "custom" && (
        <>
          <div>
            <label htmlFor="flt-from" className="mb-1 block text-xs font-semibold">From</label>
            <input id="flt-from" type="date" className={select} value={range.from} max={range.to} onChange={(e) => onChange({ from: e.target.value })} />
          </div>
          <div>
            <label htmlFor="flt-to" className="mb-1 block text-xs font-semibold">To</label>
            <input id="flt-to" type="date" className={select} value={range.to} min={range.from} onChange={(e) => onChange({ to: e.target.value })} />
          </div>
        </>
      )}
      <fieldset>
        <legend className="mb-1 text-xs font-semibold">Granularity</legend>
        <div className="flex overflow-hidden rounded-lg border border-stone-300">
          {GRANULARITIES.map((g) => (
            <label key={g} className={`cursor-pointer px-3 py-2 text-sm capitalize focus-within:ring-2 focus-within:ring-teal-600 ${effective === g ? "bg-navy text-white" : "bg-white text-navy hover:bg-navy-50"}`}>
              <input type="radio" name="granularity" value={g} checked={filters.granularity === g} onChange={() => onChange({ granularity: g })} className="sr-only" />
              {g}
            </label>
          ))}
        </div>
      </fieldset>
      <div>
        <label htmlFor="flt-client" className="mb-1 block text-xs font-semibold">Client</label>
        <select id="flt-client" className={`${select} max-w-48`} value={filters.client} onChange={(e) => onChange({ client: e.target.value })}>
          <option value="">All clients</option>
          {(clients.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor="flt-plan" className="mb-1 block text-xs font-semibold">Plan</label>
        <select id="flt-plan" className={select} value={filters.plan} onChange={(e) => onChange({ plan: e.target.value })}>
          <option value="">All plans</option>
          {(plans.data ?? []).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
        </select>
      </div>
      <label className="flex items-center gap-2 pb-2 text-sm">
        <input type="checkbox" checked={filters.compare} onChange={(e) => onChange({ compare: e.target.checked })} className="h-4 w-4 accent-teal-700" />
        Compare to previous period
      </label>
      <label className="flex items-center gap-2 pb-2 text-sm">
        <input type="checkbox" checked={filters.demo} onChange={(e) => onChange({ demo: e.target.checked })} className="h-4 w-4 accent-teal-700" />
        Include demo data
      </label>
      <Button type="button" variant="ghost" size="sm" className="mb-0.5" onClick={() => onChange({ ...DEFAULT_FILTERS })}>Reset</Button>
      {effective !== filters.granularity && <p role="status" className="basis-full text-xs text-stone-600">Daily buckets over this range are too dense, so weekly buckets are shown.</p>}
    </form>
  );
}
