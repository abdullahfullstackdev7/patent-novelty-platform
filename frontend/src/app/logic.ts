// Pure helpers for the claim chart, case lists and run progress. Kept free of React so they are easy to test.

import type { Cell, CellStatus, CaseItem, Chart } from "@/app/types";

export const STATUS_ORDER: CellStatus[] = ["disclosed", "partial", "not_found"];

export const STATUS_META: Record<CellStatus, { label: string; short: string; key: string; tone: "high" | "medium" | "low" }> = {
  disclosed: { label: "Disclosed", short: "D", key: "1", tone: "high" },
  partial: { label: "Partial", short: "P", key: "2", tone: "medium" },
  not_found: { label: "Not found", short: "N", key: "3", tone: "low" },
};

/** Keyboard shortcut digit to status, as shown in the legend. */
export function statusForKey(key: string): CellStatus | null {
  return STATUS_ORDER.find((s) => STATUS_META[s].key === key) ?? null;
}

export type Grid = Map<string, Map<string, Cell>>; // element key -> patent id -> cell

export function buildGrid(chart: Pick<Chart, "cells">): Grid {
  const grid: Grid = new Map();
  for (const cell of chart.cells) {
    if (!grid.has(cell.element)) grid.set(cell.element, new Map());
    grid.get(cell.element)!.set(cell.patent_id, cell);
  }
  return grid;
}

/** The best status any reference reaches for an element: disclosed beats partial beats not found. */
export function bestStatus(cells: Cell[]): CellStatus | null {
  if (!cells.length) return null;
  for (const s of STATUS_ORDER) if (cells.some((c) => c.status === s)) return s;
  return null;
}

export function elementCoverage(grid: Grid, elementKey: string, references?: string[]): CellStatus | null {
  const row = grid.get(elementKey);
  if (!row) return null;
  const cells = [...row.entries()].filter(([patent]) => !references || references.includes(patent)).map(([, c]) => c);
  return bestStatus(cells);
}

/** Elements no reference discloses (fully or partly). */
export function uncoveredElements(chart: Chart): string[] {
  const grid = buildGrid(chart);
  return chart.elements
    .filter((e) => {
      const best = elementCoverage(grid, e.id);
      return best === null || best === "not_found";
    })
    .map((e) => e.id);
}

export function coverageSummary(chart: Chart, patentId: string) {
  const counts: Record<CellStatus, number> = { disclosed: 0, partial: 0, not_found: 0 };
  for (const c of chart.cells) if (c.patent_id === patentId) counts[c.status] += 1;
  const total = counts.disclosed + counts.partial + counts.not_found;
  return { ...counts, total, percent: total ? Math.round(((counts.disclosed + counts.partial * 0.5) / total) * 100) : 0 };
}

/** Moves the selection by `delta` inside `keys`, stopping at the ends. */
export function moveSelection(keys: string[], current: string | null, delta: number): string | null {
  if (!keys.length) return null;
  const index = current ? keys.indexOf(current) : -1;
  if (index === -1) return delta >= 0 ? keys[0] : keys[keys.length - 1];
  return keys[Math.min(keys.length - 1, Math.max(0, index + delta))];
}

/** Splits an excerpt around the stored character range so it can be highlighted. Falls back to no highlight. */
export function highlightParts(text: string, start: number | null, end: number | null): { before: string; match: string; after: string } {
  if (start === null || end === null || start < 0 || end > text.length || start >= end) return { before: "", match: text, after: "" };
  return { before: text.slice(0, start), match: text.slice(start, end), after: text.slice(end) };
}

export function confidenceLabel(value: number): "High" | "Medium" | "Low" {
  return value >= 0.75 ? "High" : value >= 0.45 ? "Medium" : "Low";
}

// ---- cases ------------------------------------------------------------------------------------------------

export const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  running: "Running",
  ready: "Ready",
  in_review: "In review",
  approved: "Approved",
  changes_requested: "Changes requested",
  failed: "Failed",
};

export const statusLabel = (s: string) => STATUS_LABEL[s] ?? s.replace(/_/g, " ");

export interface CaseFilters {
  status: string;
  risk: string;
  mine: boolean;
  from: string;
  to: string;
  search: string;
}

export const EMPTY_FILTERS: CaseFilters = { status: "", risk: "", mine: false, from: "", to: "", search: "" };

export function filterCases(items: CaseItem[], f: CaseFilters, userId: string | undefined): CaseItem[] {
  const q = f.search.trim().toLowerCase();
  return items.filter((c) => {
    if (f.status && c.status !== f.status) return false;
    if (f.risk && (c.risk_level ?? "none") !== f.risk) return false;
    if (f.mine && c.owner_id !== userId) return false;
    if (f.from && c.created_at.slice(0, 10) < f.from) return false;
    if (f.to && c.created_at.slice(0, 10) > f.to) return false;
    if (q && !c.title.toLowerCase().includes(q)) return false;
    return true;
  });
}

export type SortKey = "title" | "status" | "risk_score" | "updated_at" | "created_at";

export function sortCases(items: CaseItem[], key: SortKey, dir: "asc" | "desc"): CaseItem[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const av = a[key] ?? (key === "risk_score" ? -1 : "");
    const bv = b[key] ?? (key === "risk_score" ? -1 : "");
    return (av < bv ? -1 : av > bv ? 1 : 0) * sign;
  });
}

export function caseKpis(items: CaseItem[], now = new Date()) {
  const month = now.toISOString().slice(0, 7);
  const approved = items.filter((c) => c.status === "approved");
  const turnaround = approved.map((c) => new Date(c.updated_at).getTime() - new Date(c.created_at).getTime()).filter((ms) => ms >= 0);
  return {
    open: items.filter((c) => !["approved", "failed"].includes(c.status)).length,
    awaitingReview: items.filter((c) => c.status === "in_review").length,
    approvedThisMonth: approved.filter((c) => c.updated_at.slice(0, 7) === month).length,
    avgTurnaroundHours: turnaround.length ? turnaround.reduce((a, b) => a + b, 0) / turnaround.length / 3_600_000 : null,
  };
}

export function formatDuration(hours: number | null): string {
  if (hours === null) return "n/a";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${(hours / 24).toFixed(1)} days`;
}

export function paginate<T>(items: T[], page: number, size: number) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(1, page), pages);
  return { rows: items.slice((current - 1) * size, current * size), page: current, pages };
}

// ---- run progress ---------------------------------------------------------------------------------------------

export const PIPELINE_STAGES = [
  { id: "intake", label: "Reading the disclosure" },
  { id: "search", label: "Searching the corpus" },
  { id: "reference_selection", label: "Selecting references" },
  { id: "passage_selection", label: "Selecting passages" },
  { id: "charting", label: "Charting elements" },
  { id: "risk", label: "Assessing risk" },
  { id: "report", label: "Drafting the report" },
  { id: "done", label: "Done" },
] as const;

export type StageState = "done" | "active" | "pending" | "failed";

export function stageStates(stage: string | null, jobStatus: string): { id: string; label: string; state: StageState }[] {
  const index = PIPELINE_STAGES.findIndex((s) => s.id === stage);
  const failed = jobStatus === "failed";
  return PIPELINE_STAGES.map((s, i) => {
    let state: StageState = "pending";
    if (stage === "done" || jobStatus === "succeeded") state = "done";
    else if (index === -1) state = "pending";
    else if (i < index) state = "done";
    else if (i === index) state = failed ? "failed" : "active";
    return { id: s.id, label: s.label, state };
  });
}

export const isFinalJob = (status: string) => ["succeeded", "failed", "cancelled", "idle", "deleted"].includes(status);

export function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ---- elements (wizard) -------------------------------------------------------------------------------------------

export interface DraftElement {
  uid: string;
  text: string;
  source: "user" | "llm" | "local";
}

export function moveItem<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length || from === to) return list;
  const copy = [...list];
  const [item] = copy.splice(from, 1);
  copy.splice(to, 0, item);
  return copy;
}

/** Splits an element at the cursor into two. Empty halves are not created. */
export function splitElement(list: DraftElement[], index: number, at: number, uid: string): DraftElement[] {
  const el = list[index];
  const left = el.text.slice(0, at).trim();
  const right = el.text.slice(at).trim();
  if (!left || !right) return list;
  const copy = [...list];
  copy.splice(index, 1, { ...el, text: left }, { uid, text: right, source: "user" });
  return copy;
}

/** Merges an element with the one after it. */
export function mergeWithNext(list: DraftElement[], index: number): DraftElement[] {
  if (index < 0 || index >= list.length - 1) return list;
  const copy = [...list];
  const [a, b] = [copy[index], copy[index + 1]];
  copy.splice(index, 2, { ...a, text: `${a.text.replace(/[;,.]\s*$/, "")}; ${b.text}`.trim(), source: "user" });
  return copy;
}

export function validateDisclosure(d: { title: string; technical_field: string; problem: string; solution: string }): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!d.title.trim()) errors.title = "Enter a title";
  if (d.problem.trim().length < 20) errors.problem = "Describe the problem in at least 20 characters";
  if (d.solution.trim().length < 20) errors.solution = "Describe the solution in at least 20 characters";
  return errors;
}
