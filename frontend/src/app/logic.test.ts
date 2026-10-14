import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTERS,
  STATUS_META,
  buildGrid,
  caseKpis,
  confidenceLabel,
  coverageSummary,
  elementCoverage,
  filterCases,
  formatDuration,
  formatElapsed,
  highlightParts,
  isFinalJob,
  mergeWithNext,
  moveItem,
  moveSelection,
  paginate,
  sortCases,
  splitElement,
  stageStates,
  statusForKey,
  uncoveredElements,
  validateDisclosure,
  type DraftElement,
} from "@/app/logic";
import { CASES, CHART } from "@/test/backend";

describe("coverage status logic", () => {
  const grid = buildGrid(CHART);

  it("maps keyboard digits to statuses and back", () => {
    expect(statusForKey("1")).toBe("disclosed");
    expect(statusForKey("2")).toBe("partial");
    expect(statusForKey("3")).toBe("not_found");
    expect(statusForKey("4")).toBeNull();
    expect(Object.values(STATUS_META).map((m) => m.key)).toEqual(["1", "2", "3"]);
  });

  it("takes the best status across references: disclosed beats partial beats not found", () => {
    expect(elementCoverage(grid, "E1")).toBe("disclosed");
    expect(elementCoverage(grid, "E2")).toBe("partial");
    expect(elementCoverage(grid, "E3")).toBe("not_found");
    expect(elementCoverage(grid, "E1", ["US200B2"])).toBe("not_found"); // only the second reference counts
    expect(elementCoverage(grid, "E9")).toBeNull();
  });

  it("lists elements that no reference discloses, fully or partly", () => {
    expect(uncoveredElements(CHART)).toEqual(["E3"]);
    const better = { ...CHART, cells: CHART.cells.map((c) => (c.id === "k6" ? { ...c, status: "partial" as const } : c)) };
    expect(uncoveredElements(better)).toEqual([]);
  });

  it("summarises one reference with partial matches counting half", () => {
    expect(coverageSummary(CHART, "US100A1")).toEqual({ disclosed: 1, partial: 1, not_found: 1, total: 3, percent: 50 });
    expect(coverageSummary(CHART, "US200B2").percent).toBe(0);
    expect(coverageSummary(CHART, "nope")).toMatchObject({ total: 0, percent: 0 });
  });

  it("moves the selection with J and K and stops at the ends", () => {
    const keys = ["E1", "E2", "E3"];
    expect(moveSelection(keys, null, 1)).toBe("E1");
    expect(moveSelection(keys, null, -1)).toBe("E3");
    expect(moveSelection(keys, "E1", 1)).toBe("E2");
    expect(moveSelection(keys, "E3", 1)).toBe("E3");
    expect(moveSelection(keys, "E1", -1)).toBe("E1");
    expect(moveSelection(keys, "gone", 1)).toBe("E1");
    expect(moveSelection([], "E1", 1)).toBeNull();
  });

  it("splits an excerpt around the stored range and ignores invalid ranges", () => {
    expect(highlightParts("the quick brown fox", 4, 9)).toEqual({ before: "the ", match: "quick", after: " brown fox" });
    expect(highlightParts("abc", null, null)).toEqual({ before: "", match: "abc", after: "" });
    expect(highlightParts("abc", 2, 99)).toEqual({ before: "", match: "abc", after: "" });
    expect(highlightParts("abc", 2, 2)).toEqual({ before: "", match: "abc", after: "" });
    expect(highlightParts("abc", -1, 2)).toEqual({ before: "", match: "abc", after: "" });
  });

  it("labels confidence", () => {
    expect([0.9, 0.75, 0.6, 0.45, 0.1].map(confidenceLabel)).toEqual(["High", "High", "Medium", "Medium", "Low"]);
  });
});

describe("case list logic", () => {
  it("filters by status, risk, owner, date and title", () => {
    expect(filterCases(CASES, { ...EMPTY_FILTERS, status: "in_review" }, "u-attorney").map((c) => c.id)).toEqual(["c2"]);
    expect(filterCases(CASES, { ...EMPTY_FILTERS, risk: "none" }, "u-attorney").map((c) => c.id)).toEqual(["c3"]);
    expect(filterCases(CASES, { ...EMPTY_FILTERS, risk: "high" }, "u-attorney").map((c) => c.id)).toEqual(["c1"]);
    expect(filterCases(CASES, { ...EMPTY_FILTERS, mine: true }, "u-attorney")).toHaveLength(3);
    expect(filterCases(CASES, { ...EMPTY_FILTERS, search: "COOLING" }, "x").map((c) => c.id)).toEqual(["c2"]);
    expect(filterCases(CASES, { ...EMPTY_FILTERS, from: "2026-09-02" }, "x")).toHaveLength(0);
    expect(filterCases(CASES, { ...EMPTY_FILTERS, to: "2026-08-31" }, "x")).toHaveLength(0);
  });

  it("sorts ascending and descending, putting unassessed risk last when descending", () => {
    expect(sortCases(CASES, "title", "asc")[0].title).toBe("Adaptive cooling manifold");
    expect(sortCases(CASES, "risk_score", "desc")[0].id).toBe("c1");
    expect(sortCases(CASES, "risk_score", "desc").at(-1)!.id).toBe("c3");
    expect(CASES[0].id).toBe("c1"); // the input is not mutated
  });

  it("computes the KPIs", () => {
    const k = caseKpis(CASES, new Date("2026-09-15T00:00:00Z"));
    expect(k.open).toBe(3);
    expect(k.awaitingReview).toBe(1);
    expect(k.approvedThisMonth).toBe(10);
    expect(k.avgTurnaroundHours).toBeCloseTo(4, 5);
    expect(caseKpis([]).avgTurnaroundHours).toBeNull();
  });

  it("formats durations and paginates safely", () => {
    expect(formatDuration(null)).toBe("n/a");
    expect(formatDuration(0.2)).toBe("12 min");
    expect(formatDuration(5)).toBe("5.0 h");
    expect(formatDuration(72)).toBe("3.0 days");
    const p = paginate([1, 2, 3, 4, 5], 9, 2);
    expect(p).toEqual({ rows: [5], page: 3, pages: 3 });
    expect(paginate([], 1, 10)).toEqual({ rows: [], page: 1, pages: 1 });
  });
});

describe("run progress logic", () => {
  it("marks earlier stages done, the current one active and later ones pending", () => {
    const s = stageStates("charting", "running");
    expect(s.map((x) => x.state)).toEqual(["done", "done", "done", "done", "active", "pending", "pending", "pending"]);
  });

  it("shows the failed stage and completes everything on success", () => {
    expect(stageStates("search", "failed").find((x) => x.id === "search")!.state).toBe("failed");
    expect(stageStates("done", "succeeded").every((x) => x.state === "done")).toBe(true);
    expect(stageStates(null, "queued").every((x) => x.state === "pending")).toBe(true);
  });

  it("knows which job states are final and formats elapsed time", () => {
    expect(["succeeded", "failed", "cancelled", "idle", "deleted"].every(isFinalJob)).toBe(true);
    expect(isFinalJob("running")).toBe(false);
    expect(formatElapsed(65)).toBe("1:05");
    expect(formatElapsed(3)).toBe("0:03");
  });
});

describe("element editing logic", () => {
  const list: DraftElement[] = [
    { uid: "a", text: "a sensor; and a probe", source: "llm" },
    { uid: "b", text: "a controller", source: "llm" },
    { uid: "c", text: "a loop", source: "llm" },
  ];

  it("reorders without mutating and ignores out-of-range moves", () => {
    expect(moveItem(list, 0, 2).map((e) => e.uid)).toEqual(["b", "c", "a"]);
    expect(moveItem(list, 0, -1)).toBe(list);
    expect(moveItem(list, 2, 3)).toBe(list);
    expect(list.map((e) => e.uid)).toEqual(["a", "b", "c"]);
  });

  it("splits at the cursor into two user-edited elements and refuses empty halves", () => {
    const out = splitElement(list, 0, "a sensor;".length, "n");
    expect(out.map((e) => e.text)).toEqual(["a sensor;", "and a probe", "a controller", "a loop"]);
    expect(out[1]).toMatchObject({ uid: "n", source: "user" });
    expect(splitElement(list, 0, 0, "n")).toBe(list);
    expect(splitElement(list, 0, 999, "n")).toBe(list);
  });

  it("merges with the next element and marks the result as user-edited", () => {
    const out = mergeWithNext(list, 1);
    expect(out).toHaveLength(2);
    expect(out[1]).toMatchObject({ uid: "b", text: "a controller; a loop", source: "user" });
    expect(mergeWithNext(list, 2)).toBe(list);
  });

  it("validates the disclosure fields", () => {
    expect(validateDisclosure({ title: "", technical_field: "", problem: "short", solution: "" })).toEqual({
      title: "Enter a title",
      problem: "Describe the problem in at least 20 characters",
      solution: "Describe the solution in at least 20 characters",
    });
    expect(validateDisclosure({ title: "T", technical_field: "", problem: "x".repeat(20), solution: "y".repeat(20) })).toEqual({});
  });
});
