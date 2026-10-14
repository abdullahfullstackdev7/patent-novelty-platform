import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/app/client";

export interface Meta {
  includes_demo?: boolean;
  demo_through?: string | null;
  refreshed_at?: string;
  [key: string]: unknown;
}

export interface Rows<R> {
  meta: Meta;
  rows: R[];
  [key: string]: unknown;
}

export type Query = Record<string, string | number | boolean | undefined>;

/** One analytics request. Previous data stays on screen while a new filter loads, so charts do not flash empty. */
export function useAnalytics<T>(path: string, query: Query, enabled = true) {
  return useQuery({
    queryKey: ["analytics", path, query],
    queryFn: () => api<T>(`/analytics${path}`, { query }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    enabled,
  });
}

/** Downloads the CSV that backs a chart, using the same filters as the chart itself. */
export async function downloadCsv(path: string, query: Query, filename: string): Promise<void> {
  const response = await api<Response>(`/analytics${path}`, { raw: true, query: { ...query, format: "csv" } });
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// ---- row shapes returned by the API ---------------------------------------------------------------------------

export interface Kpi {
  value: number | null;
  previous: number | null;
  delta: number | null;
  delta_pct: number | null;
  sparkline: (number | null)[];
}
export interface KpiSummary extends Meta {
  kpis: Record<"mrr" | "arr" | "nrr" | "arpa" | "collections_rate" | "receivables", Kpi>;
  meta: Meta;
  active_clients: number;
}
export interface SeriesPoint {
  period: string;
  value: number | null;
  previous_period?: string;
  previous?: number | null;
}
export interface BreakdownRow {
  key: string;
  label: string;
  revenue: number;
  subscription: number;
  addon: number;
  overage: number;
  clients: number;
  share_pct: number;
  reports?: number;
  trend_pct?: number;
}
export interface AgingRow {
  bucket: string;
  invoices: number;
  amount: number;
}
export interface AgingResponse extends Rows<AgingRow> {
  statuses: { status: string; invoices: number; amount: number }[];
}
export interface CohortResponse extends Rows<unknown> {
  matrix: { cohort: string; size: number; retention: Record<string, number | null> }[];
}
export interface MarginRow {
  month: string;
  revenue: number;
  token_cost: number;
  infra_cost: number;
  gross_margin: number;
  gross_margin_pct: number;
}
export interface TurnaroundResponse extends Rows<{ bucket: string; cases: number }> {
  summary: { cases: number; mean_hours: number | null; p50_hours: number | null; p90_hours: number | null };
  trend: { month: string; cases: number; p50_hours: number | null; p90_hours: number | null }[];
}
export interface CpcResponse extends Rows<{ subclass: string; votes: number; searches: number }> {
  heatmap: { month: string; subclass: string; votes: number }[];
}
export interface AttorneyRow {
  user_id: string;
  name: string;
  role: string;
  is_demo: boolean;
  cases: number;
  approved: number;
  in_review: number;
}
export interface EfficiencyRow {
  month: string;
  calls: number;
  cache_hit_rate: number;
  fallback_rate: number;
  tokens: number;
  cases: number;
  tokens_per_case: number;
  target: number;
}
export interface EfficiencyResponse extends Rows<EfficiencyRow> {
  quota?: {
    name: string;
    model: string;
    configured: boolean;
    day: { tokens_used: number; tokens_limit: number; tokens_percent: number; requests_used: number; requests_limit: number; requests_percent: number };
  }[];
}
export interface CostRow {
  month: string;
  cost: number;
  cases: number;
  cost_per_case: number;
  revenue: number;
  reports: number;
  revenue_per_case: number;
  margin_per_case: number;
}
export interface WalkRowApi {
  month: string;
  opening: number;
  new: number;
  expansion: number;
  contraction: number;
  churn: number;
  closing: number;
  new_clients: number;
  churned_clients: number;
  active_clients: number;
}
