// Pure helpers for the analytics dashboard: filter handling, number formatting and chart data shaping.
// Nothing here knows about React or ECharts, so every function can be tested directly.

export type Preset = "30d" | "90d" | "12m" | "24m" | "custom";
export type Granularity = "day" | "week" | "month";

export interface AnalyticsFilters {
  preset: Preset;
  from: string; // used when preset is custom
  to: string;
  granularity: Granularity;
  compare: boolean;
  client: string; // "" for all
  plan: string; // "" for all
  demo: boolean;
}

export const PRESET_LABEL: Record<Preset, string> = {
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  "12m": "Last 12 months",
  "24m": "Last 24 months",
  custom: "Custom range",
};

export const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const parseIso = (s: string) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};
export const monthStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1);
export const addMonths = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth() + n, 1);
export const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

export const DEFAULT_FILTERS: AnalyticsFilters = { preset: "12m", from: "", to: "", granularity: "month", compare: false, client: "", plan: "", demo: true };

/** Date range for a preset. Month based presets start on the first of a month so monthly buckets are whole. */
export function presetRange(preset: Preset, today: Date, custom?: { from: string; to: string }): { from: string; to: string } {
  const end = iso(today);
  switch (preset) {
    case "30d":
      return { from: iso(addDays(today, -29)), to: end };
    case "90d":
      return { from: iso(addDays(today, -89)), to: end };
    case "12m":
      return { from: iso(addMonths(monthStart(today), -11)), to: end };
    case "24m":
      return { from: iso(addMonths(monthStart(today), -23)), to: end };
    default: {
      const from = custom?.from || iso(addMonths(monthStart(today), -11));
      const to = custom?.to || end;
      return from <= to ? { from, to } : { from: to, to: from };
    }
  }
}

export function rangeOf(f: AnalyticsFilters, today: Date) {
  return presetRange(f.preset, today, { from: f.from, to: f.to });
}

/** Query parameters shared by every analytics endpoint. */
export function filterQuery(f: AnalyticsFilters, today: Date): Record<string, string | boolean> {
  const r = rangeOf(f, today);
  const q: Record<string, string | boolean> = { from: r.from, to: r.to, include_demo: f.demo };
  if (f.client) q.client_id = f.client;
  if (f.plan) q.plan = f.plan;
  return q;
}

/** Series that only exist per month ignore a day or week choice. */
export const effectiveGranularity = (g: Granularity, monthlyOnly: boolean): Granularity => (monthlyOnly ? "month" : g);

/** Day buckets over more than a year are too dense to read, so the filter falls back to weeks. */
export function allowedGranularity(g: Granularity, from: string, to: string): Granularity {
  const days = (parseIso(to).getTime() - parseIso(from).getTime()) / 86_400_000 + 1;
  if (g === "day" && days > 400) return "week";
  return g;
}

export function movingAverage(values: (number | null)[], window = 3): (number | null)[] {
  return values.map((_, i) => {
    if (i < window - 1) return null;
    const slice = values.slice(i - window + 1, i + 1);
    if (slice.some((v) => v === null)) return null;
    return Math.round(((slice as number[]).reduce((a, b) => a + b, 0) / window) * 100) / 100;
  });
}

// ---- number formatting ---------------------------------------------------------------------------------------

export const fmtMoney = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "n/a" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);

export const fmtCompactMoney = (v: number) => {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `$${(v / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  if (abs >= 1_000) return `$${(v / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}k`;
  return `$${Math.round(v)}`;
};

export const fmtInt = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : new Intl.NumberFormat("en-US").format(Math.round(v)));
export const fmtCompactInt = (v: number) => (Math.abs(v) >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : Math.abs(v) >= 1_000 ? `${(v / 1_000).toFixed(v >= 10_000 ? 0 : 1)}k` : String(Math.round(v)));
export const fmtPct = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "n/a" : `${v.toFixed(digits)}%`);
export const fmtHours = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : v >= 48 ? `${(v / 24).toFixed(1)} days` : `${v.toFixed(1)} h`);
export const fmtMs = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);

export type KpiFormat = "money" | "percent";
export const formatKpi = (value: number | null, format: KpiFormat) => (format === "money" ? fmtMoney(value) : fmtPct(value));

/** "+3.7%" style text and a direction for the arrow. Missing values read as no change data. */
export function deltaText(delta: number | null, pct: number | null): { text: string; direction: "up" | "down" | "flat" } {
  if (delta === null || pct === null) return { text: "No prior period", direction: "flat" };
  const direction = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const sign = delta > 0 ? "+" : "";
  return { text: `${sign}${pct.toFixed(1)}% vs previous month`, direction };
}

// ---- data shaping -----------------------------------------------------------------------------------------------

export interface WalkRow {
  month: string;
  opening: number;
  new: number;
  expansion: number;
  contraction: number;
  churn: number;
  closing: number;
}

/** Floating-bar data for a waterfall: an invisible base plus rising and falling steps. */
export function waterfall(rows: WalkRow[]) {
  if (!rows.length) return null;
  const sum = (k: "new" | "expansion" | "contraction" | "churn") => rows.reduce((a, r) => a + r[k], 0);
  const opening = rows[0].opening;
  const steps = [
    { label: "Opening MRR", kind: "total" as const, value: opening },
    { label: "New", kind: "up" as const, value: sum("new") },
    { label: "Expansion", kind: "up" as const, value: sum("expansion") },
    { label: "Contraction", kind: "down" as const, value: sum("contraction") },
    { label: "Churn", kind: "down" as const, value: sum("churn") },
    { label: "Closing MRR", kind: "total" as const, value: rows[rows.length - 1].closing },
  ];
  let running = 0;
  const base: number[] = [];
  const up: number[] = [];
  const down: number[] = [];
  const total: number[] = [];
  for (const s of steps) {
    if (s.kind === "total") {
      base.push(0);
      up.push(0);
      down.push(0);
      total.push(s.value);
      running = s.value;
    } else if (s.kind === "up") {
      base.push(running);
      up.push(s.value);
      down.push(0);
      total.push(0);
      running += s.value;
    } else {
      running -= s.value;
      base.push(running);
      up.push(0);
      down.push(s.value);
      total.push(0);
    }
  }
  const expectedClosing = opening + sum("new") + sum("expansion") - sum("contraction") - sum("churn");
  return { labels: steps.map((s) => s.label), base, up, down, total, steps, reconciles: Math.abs(expectedClosing - steps[5].value) < 1 };
}

export interface CohortRow {
  cohort: string;
  size: number;
  retention: Record<string, number | null>;
}

/** [x = months since signup, y = cohort index, value] triples for a heatmap, skipping months that have not happened yet. */
export function cohortCells(matrix: CohortRow[], maxMonths = 24): { cohorts: string[]; months: number[]; cells: [number, number, number][] } {
  const cohorts = matrix.map((r) => r.cohort);
  const months = Array.from({ length: maxMonths + 1 }, (_, i) => i);
  const cells: [number, number, number][] = [];
  matrix.forEach((row, y) => {
    for (const m of months) {
      const v = row.retention[String(m)];
      if (v !== undefined && v !== null) cells.push([m, y, v]);
    }
  });
  return { cohorts, months, cells };
}

export interface TokenRow {
  period: string;
  provider: string;
  tokens: number;
}

export function pivotTokens(rows: TokenRow[]) {
  const periods = [...new Set(rows.map((r) => r.period))].sort();
  const providers = [...new Set(rows.map((r) => r.provider))].sort();
  const lookup = new Map(rows.map((r) => [`${r.period}|${r.provider}`, r.tokens]));
  return { periods, providers, series: providers.map((p) => ({ provider: p, values: periods.map((d) => lookup.get(`${d}|${p}`) ?? 0) })) };
}

export interface HeatRow {
  month: string;
  subclass: string;
  votes: number;
}

export function heatGrid(rows: HeatRow[]) {
  const months = [...new Set(rows.map((r) => r.month))].sort();
  const subclasses = [...new Set(rows.map((r) => r.subclass))].sort();
  const cells: [number, number, number][] = rows.map((r) => [months.indexOf(r.month), subclasses.indexOf(r.subclass), r.votes]);
  return { months, subclasses, cells, max: Math.max(0, ...rows.map((r) => r.votes)) };
}

/** Label for a bucket start date, matched to the granularity. */
export function periodLabel(period: string, g: Granularity): string {
  const d = parseIso(period);
  if (g === "month") return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
export const round2 = (v: number) => Math.round(v * 100) / 100;

/** The largest absolute difference between two same-length series, used to prove stacked parts equal the total. */
export function maxGap(a: number[], b: number[]): number {
  return Math.max(0, ...a.map((v, i) => Math.abs(v - (b[i] ?? 0))));
}

export function csvName(base: string, f: AnalyticsFilters, today: Date): string {
  const r = rangeOf(f, today);
  return `${base}_${r.from}_${r.to}.csv`;
}

export function demoNote(meta: { includes_demo?: boolean; demo_through?: string | null } | undefined): string | null {
  if (!meta?.includes_demo || !meta.demo_through) return null;
  return `Includes demo data through ${parseIso(meta.demo_through.slice(0, 10)).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}`;
}
