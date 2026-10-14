import { ExternalLink, Info, Printer } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { CoverageChip, EmptyState, ErrorState, Loading, messageOf, useToast } from "@/app/components/feedback";
import { useChart, useOverrideCell, useResults } from "@/app/hooks";
import {
  STATUS_META,
  STATUS_ORDER,
  buildGrid,
  confidenceLabel,
  coverageSummary,
  elementCoverage,
  highlightParts,
  moveSelection,
  statusForKey,
  uncoveredElements,
} from "@/app/logic";
import type { Cell, CellStatus } from "@/app/types";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlay";
import { cn } from "@/lib/utils";

function Excerpt({ cell }: { cell: Cell }) {
  if (!cell.excerpt) return <p className="rounded-lg bg-stone-50 p-4 text-stone-700">No passage in this reference matches this element.</p>;
  const { before, match, after } = highlightParts(cell.excerpt, cell.char_start, cell.char_end);
  return (
    <blockquote className="rounded-lg border-l-4 border-teal-600 bg-stone-50 p-4 font-mono text-sm leading-relaxed text-navy">
      {before}
      <mark className="rounded bg-yellow-200 px-0.5 text-navy">{match}</mark>
      {after}
    </blockquote>
  );
}

function Confidence({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-28 rounded-full bg-stone-200" role="meter" aria-label="Confidence" aria-valuemin={0} aria-valuemax={1} aria-valuenow={value}>
        <div className="h-2 rounded-full bg-teal-600" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="text-sm text-stone-700">{confidenceLabel(value)} ({Math.round(value * 100)}%)</span>
    </div>
  );
}

export function ChartViewer({ caseId, canEdit, ran }: { caseId: string; canEdit: boolean; ran: boolean }) {
  const chartQ = useChart(caseId, ran);
  const resultsQ = useResults(caseId, ran);
  const override = useOverrideCell(caseId);
  const toast = useToast();
  const [selected, setSelected] = useState<string | null>(null);
  const [patent, setPatent] = useState<string | null>(null);
  const [onlyUncovered, setOnlyUncovered] = useState(false);
  const [dialog, setDialog] = useState<{ cell: Cell; status: CellStatus } | null>(null);
  const [reason, setReason] = useState("");
  const [drawer, setDrawer] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const chart = chartQ.data;
  const grid = useMemo(() => (chart ? buildGrid(chart) : null), [chart]);
  const uncovered = useMemo(() => (chart ? new Set(uncoveredElements(chart)) : new Set<string>()), [chart]);
  const visible = useMemo(() => (chart ? chart.elements.filter((e) => !onlyUncovered || uncovered.has(e.id)) : []), [chart, onlyUncovered, uncovered]);
  const keysList = useMemo(() => visible.map((e) => e.id), [visible]);

  const activePatent = patent && chart?.references.includes(patent) ? patent : chart?.references[0] ?? null;
  const activeElement = selected && keysList.includes(selected) ? selected : keysList[0] ?? null;
  const cell = grid && activeElement && activePatent ? grid.get(activeElement)?.get(activePatent) ?? null : null;
  const meta = resultsQ.data?.results.find((r) => r.patent_id === activePatent);

  // Keyboard shortcuts: J and K move between elements, 1 2 3 start an override with that status.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || dialog || drawer) return;
      if (t && (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable)) return;
      if (!rootRef.current?.contains(document.activeElement) && document.activeElement !== document.body) return;
      const k = e.key.toLowerCase();
      if (k === "j" || k === "k") {
        e.preventDefault();
        setSelected(moveSelection(keysList, activeElement, k === "j" ? 1 : -1));
      } else if (canEdit && cell && statusForKey(k)) {
        e.preventDefault();
        setReason("");
        setDialog({ cell, status: statusForKey(k)! });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keysList, activeElement, cell, canEdit, dialog, drawer]);

  useEffect(() => {
    if (activeElement) document.getElementById(`el-btn-${activeElement}`)?.scrollIntoView?.({ block: "nearest" });
  }, [activeElement]);

  if (!ran) return <EmptyState title="No claim chart yet" text="Run the analysis to compare each element with the closest references." />;
  if (chartQ.isLoading) return <Loading rows={6} label="Loading claim chart" />;
  if (chartQ.isError) return <ErrorState error={chartQ.error} onRetry={() => chartQ.refetch()} />;
  if (!chart || !grid || chart.elements.length === 0 || chart.references.length === 0) {
    return <EmptyState title="The chart is empty" text="The run produced no charted references. Try running again with more references." />;
  }

  async function submitOverride() {
    if (!dialog) return;
    try {
      await override.mutateAsync({ cellId: dialog.cell.id, status: dialog.status, reason: reason.trim() });
      toast.success("Status updated", "The change and your reason are recorded in the activity log.");
      setDialog(null);
    } catch (e) {
      toast.error("Could not update the status", messageOf(e));
    }
  }

  const summary = activePatent ? coverageSummary(chart, activePatent) : null;
  const elementText = (key: string) => chart.elements.find((e) => e.id === key)?.text ?? key;

  return (
    <div ref={rootRef} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <ul className="flex flex-wrap items-center gap-2" aria-label="Legend">
          {STATUS_ORDER.map((s) => (
            <li key={s} className="flex items-center gap-1.5">
              <CoverageChip status={s} />
              <kbd className="rounded border border-stone-300 bg-white px-1.5 font-mono text-xs text-stone-700" aria-label={`Shortcut ${STATUS_META[s].key}`}>{STATUS_META[s].key}</kbd>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={onlyUncovered} onChange={(e) => setOnlyUncovered(e.target.checked)} className="h-4 w-4 accent-teal-700" />
            Show only uncovered elements ({uncovered.size})
          </label>
          <Button variant="outline" size="sm" onClick={() => window.print()}><Printer className="h-4 w-4" aria-hidden="true" /> Print</Button>
        </div>
      </div>
      <p className="flex items-center gap-2 text-sm text-stone-600 print:hidden"><Info className="h-4 w-4" aria-hidden="true" /> Press <kbd className="rounded border border-stone-300 px-1 font-mono">J</kbd> and <kbd className="rounded border border-stone-300 px-1 font-mono">K</kbd> to move between elements{canEdit ? ", and 1, 2 or 3 to change the status of the selected cell" : ""}.</p>

      <div className="grid gap-4 lg:grid-cols-[22rem_1fr] print:hidden">
        {/* Left pane: elements */}
        <Card className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-7rem)] lg:self-start lg:overflow-y-auto">
          <CardContent className="p-3">
            <h2 className="mb-2 px-2 text-base">Elements</h2>
            {visible.length === 0 ? <p className="p-3 text-sm text-stone-700">Every element is covered by at least one reference.</p> : (
              <ul className="space-y-1">
                {visible.map((e) => {
                  const status = activePatent ? grid.get(e.id)?.get(activePatent)?.status ?? null : null;
                  const best = elementCoverage(grid, e.id);
                  const isActive = e.id === activeElement;
                  return (
                    <li key={e.id}>
                      <button
                        id={`el-btn-${e.id}`}
                        type="button"
                        aria-current={isActive ? "true" : undefined}
                        onClick={() => setSelected(e.id)}
                        className={cn("w-full rounded-lg border p-3 text-left", isActive ? "border-teal-600 bg-teal-50" : "border-transparent hover:bg-stone-50")}
                      >
                        <span className="flex items-center justify-between gap-2">
                          <span className="font-mono text-sm font-semibold text-teal-800">{e.id}</span>
                          <CoverageChip status={status} />
                        </span>
                        <span className="mt-1 block text-sm text-navy">{e.text}</span>
                        {uncovered.has(e.id) && <span className="mt-1 block text-xs font-medium text-risk-low">No reference discloses this{best === "not_found" ? "" : " yet"}</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        {/* Right pane: reference and passage */}
        <div className="min-w-0 space-y-4">
          <div role="tablist" aria-label="References" className="flex flex-wrap gap-1 rounded-xl bg-stone-100 p-1">
            {chart.references.map((ref) => (
              <button
                key={ref}
                role="tab"
                aria-selected={ref === activePatent}
                onClick={() => setPatent(ref)}
                className={cn("rounded-lg px-3 py-2 font-mono text-sm", ref === activePatent ? "bg-white font-semibold text-navy shadow-sm" : "text-stone-700 hover:text-navy")}
              >
                {ref}
              </button>
            ))}
          </div>

          <Card>
            <CardContent>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-lg"><span className="font-mono text-teal-800">{activePatent}</span> {meta?.title}</h2>
                  <p className="mt-1 text-sm text-stone-700">{[meta?.assignee, meta?.publication_date].filter(Boolean).join(" · ") || "No assignee or date on record"}</p>
                </div>
                {meta?.url && <a href={meta.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-semibold text-teal-700 hover:underline">Open source <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></a>}
              </div>
              {summary && (
                <p className="mt-3 text-sm text-stone-700" aria-label="Coverage of this reference">
                  Covers {summary.disclosed} disclosed, {summary.partial} partial and {summary.not_found} not found of {summary.total} elements ({summary.percent}% weighted coverage).
                </p>
              )}
            </CardContent>
          </Card>

          {activeElement && (
            <Card>
              <CardContent>
                <p className="font-mono text-sm font-semibold text-teal-800">{activeElement}</p>
                <p className="mt-1 text-base font-semibold text-navy">{elementText(activeElement)}</p>
                {!cell ? (
                  <p className="mt-4 text-stone-700">This reference was not compared with this element.</p>
                ) : (
                  <div className="mt-4 space-y-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <CoverageChip status={cell.status} />
                      <Badge tone={cell.method === "llm" ? "teal" : "neutral"}>{cell.method === "llm" ? "Language model" : "Local match"}</Badge>
                      <Confidence value={cell.confidence} />
                      {cell.overridden && <Badge tone="medium">Overridden by a reviewer</Badge>}
                    </div>
                    <Excerpt cell={cell} />
                    {cell.rationale && <p className="text-base text-stone-700"><strong className="text-navy">Why: </strong>{cell.rationale}</p>}
                    {cell.overridden && (
                      <p className="rounded-lg bg-amber-50 p-3 text-sm text-risk-medium">
                        Reviewer reason: {cell.override_reason}. Original rating: {String((cell.original as { status?: string } | null)?.status ?? "unknown").replace("_", " ")}.
                      </p>
                    )}
                    <div className="flex flex-wrap gap-2">
                      {cell.excerpt && <Button variant="outline" size="sm" onClick={() => setDrawer(true)}>View passage in context</Button>}
                      {canEdit && <Button size="sm" onClick={() => { setReason(""); setDialog({ cell, status: cell.status }); }}>Override status</Button>}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Print version: the whole chart as a table */}
      <div className="hidden print:block">
        <h2 className="mb-2 text-lg">Claim chart</h2>
        <table className="w-full border-collapse text-sm">
          <thead><tr><th className="border p-2 text-left">Element</th>{chart.references.map((r) => <th key={r} className="border p-2 text-left font-mono">{r}</th>)}</tr></thead>
          <tbody>
            {chart.elements.map((e) => (
              <tr key={e.id}>
                <td className="border p-2 align-top"><strong>{e.id}</strong> {e.text}</td>
                {chart.references.map((r) => {
                  const c = grid.get(e.id)?.get(r);
                  return <td key={r} className="border p-2 align-top"><strong>{c ? STATUS_META[c.status].label : "No data"}</strong>{c?.excerpt && <><br />{c.excerpt}</>}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          {dialog && (
            <>
              <DialogTitle className="text-lg font-semibold text-navy">Override status</DialogTitle>
              <DialogDescription className="mt-2 text-base text-stone-700">{dialog.cell.element} against {dialog.cell.patent_id}. The change is recorded with your name and reason, and the risk is recalculated.</DialogDescription>
              <fieldset className="mt-4">
                <legend className="mb-1 text-sm font-semibold">New status</legend>
                <div className="flex flex-wrap gap-3">
                  {STATUS_ORDER.map((s) => (
                    <label key={s} className="flex items-center gap-2 text-base">
                      <input type="radio" name="status" checked={dialog.status === s} onChange={() => setDialog({ ...dialog, status: s })} className="accent-teal-700" /> {STATUS_META[s].label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label htmlFor="override-reason" className="mt-4 block text-sm font-semibold">Reason (required)</label>
              <textarea id="override-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-base text-navy" />
              <div className="mt-5 flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDialog(null)}>Cancel</Button>
                <Button disabled={override.isPending || reason.trim().length < 3 || dialog.status === dialog.cell.status} onClick={submitOverride}>Save override</Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={drawer} onOpenChange={setDrawer}>
        <DialogContent side="right" className="w-[min(32rem,100%)]">
          <DialogTitle className="text-lg font-semibold text-navy">Passage in {activePatent}</DialogTitle>
          <DialogDescription className="mt-1 text-sm text-stone-700">{activeElement && elementText(activeElement)}</DialogDescription>
          {cell && <div className="mt-4"><Excerpt cell={cell} /><p className="mt-3 text-sm text-stone-600">Passage {cell.passage_id ?? "id unavailable"}. The excerpt was verified word for word against the stored reference text.</p></div>}
        </DialogContent>
      </Dialog>
    </div>
  );
}
