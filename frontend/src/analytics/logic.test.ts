import { describe, expect, it } from "vitest";

import {
  DEFAULT_FILTERS,
  allowedGranularity,
  cohortCells,
  csvName,
  deltaText,
  demoNote,
  effectiveGranularity,
  filterQuery,
  fmtCompactInt,
  fmtCompactMoney,
  fmtHours,
  fmtMoney,
  fmtMs,
  fmtPct,
  heatGrid,
  maxGap,
  movingAverage,
  periodLabel,
  pivotTokens,
  presetRange,
  rangeOf,
  waterfall,
  type WalkRow,
} from "@/analytics/logic";

const TODAY = new Date(2026, 9, 14); // 14 October 2026

describe("date ranges", () => {
  it("builds each preset relative to today", () => {
    expect(presetRange("30d", TODAY)).toEqual({ from: "2026-09-15", to: "2026-10-14" });
    expect(presetRange("90d", TODAY)).toEqual({ from: "2026-07-17", to: "2026-10-14" });
    expect(presetRange("12m", TODAY)).toEqual({ from: "2025-11-01", to: "2026-10-14" });
    expect(presetRange("24m", TODAY)).toEqual({ from: "2024-11-01", to: "2026-10-14" });
  });

  it("uses the custom dates, swaps reversed ones and falls back when empty", () => {
    expect(presetRange("custom", TODAY, { from: "2026-01-05", to: "2026-02-01" })).toEqual({ from: "2026-01-05", to: "2026-02-01" });
    expect(presetRange("custom", TODAY, { from: "2026-03-01", to: "2026-02-01" })).toEqual({ from: "2026-02-01", to: "2026-03-01" });
    expect(presetRange("custom", TODAY, { from: "", to: "" })).toEqual({ from: "2025-11-01", to: "2026-10-14" });
  });

  it("turns filters into query parameters shared by every endpoint", () => {
    expect(filterQuery(DEFAULT_FILTERS, TODAY)).toEqual({ from: "2025-11-01", to: "2026-10-14", include_demo: true });
    expect(filterQuery({ ...DEFAULT_FILTERS, preset: "30d", client: "c1", plan: "starter", demo: false }, TODAY)).toEqual({
      from: "2026-09-15", to: "2026-10-14", include_demo: false, client_id: "c1", plan: "starter",
    });
    expect(rangeOf({ ...DEFAULT_FILTERS, preset: "custom", from: "2026-01-01", to: "2026-01-31" }, TODAY).from).toBe("2026-01-01");
  });

  it("keeps monthly-only series monthly and avoids unreadably dense daily charts", () => {
    expect(effectiveGranularity("day", true)).toBe("month");
    expect(effectiveGranularity("day", false)).toBe("day");
    expect(allowedGranularity("day", "2026-01-01", "2026-03-31")).toBe("day");
    expect(allowedGranularity("day", "2024-01-01", "2026-03-31")).toBe("week");
    expect(allowedGranularity("month", "2024-01-01", "2026-03-31")).toBe("month");
  });
});

describe("formatting", () => {
  it("formats money, counts, percentages and durations", () => {
    expect(fmtMoney(1234.5)).toBe("$1,235");
    expect(fmtMoney(1234.5, 2)).toBe("$1,234.50");
    expect(fmtMoney(null)).toBe("n/a");
    expect(fmtCompactMoney(950)).toBe("$950");
    expect(fmtCompactMoney(12_500)).toBe("$13k");
    expect(fmtCompactMoney(2_400)).toBe("$2.4k");
    expect(fmtCompactMoney(3_200_000)).toBe("$3.2M");
    expect(fmtCompactInt(1_250_000)).toBe("1.3M");
    expect(fmtPct(94.306)).toBe("94.3%");
    expect(fmtPct(null)).toBe("n/a");
    expect(fmtHours(5.25)).toBe("5.3 h");
    expect(fmtHours(72)).toBe("3.0 days");
    expect(fmtMs(850)).toBe("850 ms");
    expect(fmtMs(2020)).toBe("2.02 s");
  });

  it("describes a period change in words", () => {
    expect(deltaText(2186, 3.69)).toEqual({ text: "+3.7% vs previous month", direction: "up" });
    expect(deltaText(-26, -1.63)).toEqual({ text: "-1.6% vs previous month", direction: "down" });
    expect(deltaText(0, 0).direction).toBe("flat");
    expect(deltaText(null, null)).toEqual({ text: "No prior period", direction: "flat" });
  });

  it("labels buckets and the demo data note", () => {
    expect(periodLabel("2026-03-01", "month")).toBe("Mar 26");
    expect(periodLabel("2026-03-09", "week")).toBe("Mar 9");
    expect(demoNote({ includes_demo: true, demo_through: "2026-09-28" })).toBe("Includes demo data through Sep 28, 2026");
    expect(demoNote({ includes_demo: false, demo_through: "2026-09-28" })).toBeNull();
    expect(demoNote(undefined)).toBeNull();
    expect(csvName("revenue", DEFAULT_FILTERS, TODAY)).toBe("revenue_2025-11-01_2026-10-14.csv");
  });
});

describe("chart data shaping", () => {
  it("computes a trailing moving average and leaves gaps where data is missing", () => {
    expect(movingAverage([3, 6, 9, 12], 3)).toEqual([null, null, 6, 9]);
    expect(movingAverage([3, null, 9, 12], 3)).toEqual([null, null, null, null]);
    expect(movingAverage([1, 2], 3)).toEqual([null, null]);
  });

  const walkRows: WalkRow[] = [
    { month: "2026-01-01", opening: 1000, new: 200, expansion: 50, contraction: 20, churn: 30, closing: 1200 },
    { month: "2026-02-01", opening: 1200, new: 100, expansion: 0, contraction: 40, churn: 60, closing: 1200 },
  ];

  it("builds a waterfall that starts at opening MRR, ends at closing MRR and proves it adds up", () => {
    const w = waterfall(walkRows)!;
    expect(w.labels).toEqual(["Opening MRR", "New", "Expansion", "Contraction", "Churn", "Closing MRR"]);
    expect(w.steps.map((s) => s.value)).toEqual([1000, 300, 50, 60, 90, 1200]);
    expect(w.reconciles).toBe(true);
    expect(w.base).toEqual([0, 1000, 1300, 1290, 1200, 0]); // floating bars sit on the running total
    expect(w.total).toEqual([1000, 0, 0, 0, 0, 1200]);
    expect(w.up).toEqual([0, 300, 50, 0, 0, 0]);
    expect(w.down).toEqual([0, 0, 0, 60, 90, 0]);
  });

  it("flags a walk that does not add up and handles an empty range", () => {
    const broken = [{ ...walkRows[0], closing: 5000 }];
    expect(waterfall(broken)!.reconciles).toBe(false);
    expect(waterfall([])).toBeNull();
  });

  it("lays cohorts out as heatmap cells and skips months that have not happened", () => {
    const g = cohortCells([
      { cohort: "2026-01-01", size: 4, retention: { "0": 100, "1": 75, "2": null } },
      { cohort: "2026-02-01", size: 2, retention: { "0": 100 } },
    ], 3);
    expect(g.cohorts).toEqual(["2026-01-01", "2026-02-01"]);
    expect(g.cells).toEqual([[0, 0, 100], [1, 0, 75], [0, 1, 100]]);
    expect(g.months).toEqual([0, 1, 2, 3]);
  });

  it("pivots provider tokens into aligned series with zeros for gaps", () => {
    const p = pivotTokens([
      { period: "2026-02-01", provider: "gemini", tokens: 5 },
      { period: "2026-01-01", provider: "groq", tokens: 10 },
      { period: "2026-02-01", provider: "groq", tokens: 20 },
    ]);
    expect(p.periods).toEqual(["2026-01-01", "2026-02-01"]);
    expect(p.series).toEqual([{ provider: "gemini", values: [0, 5] }, { provider: "groq", values: [10, 20] }]);
  });

  it("indexes the technology heatmap by month and subclass", () => {
    const h = heatGrid([
      { month: "2026-02-01", subclass: "G06N", votes: 7 },
      { month: "2026-01-01", subclass: "A61B", votes: 3 },
    ]);
    expect(h.months).toEqual(["2026-01-01", "2026-02-01"]);
    expect(h.subclasses).toEqual(["A61B", "G06N"]);
    expect(h.cells).toContainEqual([1, 1, 7]);
    expect(h.cells).toContainEqual([0, 0, 3]);
    expect(h.max).toBe(7);
    expect(heatGrid([]).max).toBe(0);
  });

  it("measures the biggest gap between two series", () => {
    expect(maxGap([1, 2, 3], [1, 2.5, 3])).toBe(0.5);
    expect(maxGap([], [])).toBe(0);
  });
});
