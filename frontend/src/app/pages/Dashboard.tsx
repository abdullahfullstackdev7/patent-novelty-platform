import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ExternalLink, FilePlus2, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "@/app/client";
import { EmptyState, ErrorState, Loading, RiskBadge, StatusChip, messageOf, useToast } from "@/app/components/feedback";
import { PageHeader } from "@/app/components/Shell";
import { useAuth } from "@/app/auth";
import { useCases, keys } from "@/app/hooks";
import { EMPTY_FILTERS, STATUS_LABEL, caseKpis, filterCases, formatDuration, paginate, sortCases, type CaseFilters, type SortKey } from "@/app/logic";
import type { CaseItem } from "@/app/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlay";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Seo } from "@/lib/seo";

const PAGE_SIZE = 10;
const selectClass = "h-10 rounded-lg border border-stone-300 bg-white px-2 text-sm text-navy";

function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card>
      <CardContent className="p-5">
        <p className="text-sm font-medium text-stone-700">{label}</p>
        <p className="mt-1 text-2xl font-semibold text-navy">{value}</p>
        {hint && <p className="mt-1 text-xs text-stone-600">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function SortHeader({ label, k, sort, dir, onSort }: { label: string; k: SortKey; sort: SortKey; dir: "asc" | "desc"; onSort: (k: SortKey) => void }) {
  const active = sort === k;
  return (
    <TableHeader scope="col" aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="inline-flex items-center gap-1 font-semibold hover:text-teal-700" onClick={() => onSort(k)}>
        {label}
        {active && (dir === "asc" ? <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" /> : <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />)}
      </button>
    </TableHeader>
  );
}

export default function Dashboard({ listOnly = false }: { listOnly?: boolean }) {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const cases = useCases();
  const toast = useToast();
  const qc = useQueryClient();
  const [filters, setFilters] = useState<CaseFilters>({ ...EMPTY_FILTERS, search: params.get("q") ?? "" });
  const [sort, setSort] = useState<SortKey>("updated_at");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [toDelete, setToDelete] = useState<CaseItem | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => api(`/cases/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Case deleted");
      setToDelete(null);
      qc.invalidateQueries({ queryKey: keys.cases });
    },
    onError: (e) => toast.error("Could not delete the case", messageOf(e)),
  });

  const items = cases.data?.items ?? [];
  const kpis = useMemo(() => caseKpis(items), [items]);
  const view = useMemo(() => paginate(sortCases(filterCases(items, filters, user?.id), sort, dir), page, PAGE_SIZE), [items, filters, sort, dir, page, user?.id]);
  const set = (patch: Partial<CaseFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };
  const onSort = (k: SortKey) => {
    if (k === sort) setDir(dir === "asc" ? "desc" : "asc");
    else {
      setSort(k);
      setDir("desc");
    }
  };
  const canCreate = user?.role !== "viewer";
  const crumbs = listOnly ? [{ label: "Dashboard", to: "/app" }, { label: "Cases" }] : [{ label: "Dashboard" }];

  return (
    <>
      <Seo title={listOnly ? "Cases" : "Dashboard"} description="Your novelty cases." path="/app" />
      <PageHeader
        crumbs={crumbs}
        title={listOnly ? "Cases" : `Welcome, ${user?.full_name.split(" ")[0] ?? ""}`}
        subtitle={listOnly ? undefined : "Where your novelty reviews stand."}
        actions={
          canCreate && (
            <Button asChild>
              <Link to="/app/cases/new">
                <FilePlus2 className="h-4 w-4" aria-hidden="true" /> New case
              </Link>
            </Button>
          )
        }
      />

      {cases.isLoading ? (
        <Loading label="Loading cases" />
      ) : cases.isError ? (
        <ErrorState error={cases.error} onRetry={() => cases.refetch()} />
      ) : (
        <>
          <section aria-label="Key figures" className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Kpi label="Open cases" value={kpis.open} />
            <Kpi label="Awaiting review" value={kpis.awaitingReview} />
            <Kpi label="Approved this month" value={kpis.approvedThisMonth} />
            <Kpi label="Average turnaround" value={formatDuration(kpis.avgTurnaroundHours)} hint="Created to approved" />
          </section>

          {items.length === 0 ? (
            <EmptyState
              title="No cases yet"
              text="Create a case from an invention disclosure to search the corpus and chart its elements."
              action={canCreate ? <Button asChild><Link to="/app/cases/new">Create your first case</Link></Button> : undefined}
            />
          ) : (
            <Card>
              <CardContent className="p-0">
                <form className="flex flex-wrap items-end gap-3 border-b border-stone-200 p-4" role="search" aria-label="Filter cases" onSubmit={(e) => e.preventDefault()}>
                  <div>
                    <label htmlFor="f-search" className="mb-1 block text-xs font-semibold">Title</label>
                    <input id="f-search" className={`${selectClass} w-48`} value={filters.search} onChange={(e) => set({ search: e.target.value })} />
                  </div>
                  <div>
                    <label htmlFor="f-status" className="mb-1 block text-xs font-semibold">Status</label>
                    <select id="f-status" className={selectClass} value={filters.status} onChange={(e) => set({ status: e.target.value })}>
                      <option value="">All</option>
                      {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="f-risk" className="mb-1 block text-xs font-semibold">Risk</label>
                    <select id="f-risk" className={selectClass} value={filters.risk} onChange={(e) => set({ risk: e.target.value })}>
                      <option value="">All</option>
                      <option value="high">High</option>
                      <option value="medium">Medium</option>
                      <option value="low">Low</option>
                      <option value="none">Not assessed</option>
                    </select>
                  </div>
                  <div>
                    <label htmlFor="f-owner" className="mb-1 block text-xs font-semibold">Owner</label>
                    <select id="f-owner" className={selectClass} value={filters.mine ? "me" : ""} onChange={(e) => set({ mine: e.target.value === "me" })}>
                      <option value="">Everyone</option>
                      <option value="me">Me</option>
                    </select>
                  </div>
                  <div>
                    <label htmlFor="f-from" className="mb-1 block text-xs font-semibold">Created from</label>
                    <input id="f-from" type="date" className={selectClass} value={filters.from} onChange={(e) => set({ from: e.target.value })} />
                  </div>
                  <div>
                    <label htmlFor="f-to" className="mb-1 block text-xs font-semibold">to</label>
                    <input id="f-to" type="date" className={selectClass} value={filters.to} onChange={(e) => set({ to: e.target.value })} />
                  </div>
                  <Button type="button" variant="ghost" size="sm" onClick={() => set(EMPTY_FILTERS)}>Clear filters</Button>
                </form>

                {view.rows.length === 0 ? (
                  <p className="p-8 text-center text-stone-700">No cases match these filters.</p>
                ) : (
                  <Table>
                    <caption className="sr-only">Cases</caption>
                    <TableHead>
                      <TableRow>
                        <SortHeader label="Title" k="title" sort={sort} dir={dir} onSort={onSort} />
                        <SortHeader label="Status" k="status" sort={sort} dir={dir} onSort={onSort} />
                        <SortHeader label="Risk" k="risk_score" sort={sort} dir={dir} onSort={onSort} />
                        <SortHeader label="Updated" k="updated_at" sort={sort} dir={dir} onSort={onSort} />
                        <TableHeader scope="col"><span className="sr-only">Actions</span></TableHeader>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {view.rows.map((c) => (
                        <TableRow key={c.id}>
                          <TableCell>
                            <Link to={`/app/cases/${c.id}`} className="font-semibold text-navy hover:text-teal-700 hover:underline">{c.title}</Link>
                            {c.confidential && <span className="ml-2 text-xs text-stone-600">Confidential</span>}
                          </TableCell>
                          <TableCell><StatusChip status={c.status} /></TableCell>
                          <TableCell><RiskBadge level={c.risk_level} /></TableCell>
                          <TableCell><time dateTime={c.updated_at}>{new Date(c.updated_at).toLocaleDateString()}</time></TableCell>
                          <TableCell>
                            <div className="flex gap-1">
                              <Button asChild variant="ghost" size="sm"><Link to={`/app/cases/${c.id}`} aria-label={`Open ${c.title}`}><ExternalLink className="h-4 w-4" aria-hidden="true" /></Link></Button>
                              {c.permissions.delete && (
                                <Button variant="ghost" size="sm" aria-label={`Delete ${c.title}`} onClick={() => setToDelete(c)}><Trash2 className="h-4 w-4 text-risk-high" aria-hidden="true" /></Button>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
                <div className="flex items-center justify-between border-t border-stone-200 p-4 text-sm">
                  <p aria-live="polite">Page {view.page} of {view.pages}</p>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={view.page <= 1} onClick={() => setPage(view.page - 1)}>Previous</Button>
                    <Button variant="outline" size="sm" disabled={view.page >= view.pages} onClick={() => setPage(view.page + 1)}>Next</Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      <Dialog open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)}>
        <DialogContent>
          <DialogTitle className="text-lg font-semibold text-navy">Delete this case?</DialogTitle>
          <DialogDescription className="mt-2 text-base text-stone-700">
            {toDelete?.title} and its disclosure, chart and reports will be removed. This cannot be undone.
          </DialogDescription>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setToDelete(null)}>Cancel</Button>
            <Button variant="navy" disabled={remove.isPending} onClick={() => toDelete && remove.mutate(toDelete.id)}>Delete case</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
