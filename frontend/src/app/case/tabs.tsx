import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Trash2 } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/app/auth";
import { api } from "@/app/client";
import { EmptyState, ErrorState, Loading, StatusChip, messageOf, useToast } from "@/app/components/feedback";
import { useDisclosure, useResults, useReviewEvents, useUsers } from "@/app/hooks";
import type { CaseItem, Report } from "@/app/types";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/card";
import { statusLabel } from "@/app/logic";

const fmt = (iso: string) => new Date(iso).toLocaleString();

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-stone-50 p-3">
      <dt className="text-xs font-semibold uppercase tracking-wide text-stone-600">{label}</dt>
      <dd className="mt-0.5 text-base text-navy">{children}</dd>
    </div>
  );
}

interface Share {
  user_id: string;
  email: string;
  full_name: string;
  permission: string;
}

function SharingPanel({ c }: { c: CaseItem }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const shares = useQuery({ queryKey: ["case", c.id, "shares"], queryFn: () => api<Share[]>(`/cases/${c.id}/shares`), enabled: c.permissions.share });
  const users = useUsers();
  const [pick, setPick] = useState("");
  const [permission, setPermission] = useState<"read" | "write">("read");
  const refresh = () => qc.invalidateQueries({ queryKey: ["case", c.id, "shares"] });
  const add = useMutation({
    mutationFn: () => api(`/cases/${c.id}/shares`, { method: "POST", body: { user_id: pick, permission } }),
    onSuccess: () => { toast.success("Case shared"); setPick(""); refresh(); },
    onError: (e) => toast.error("Could not share the case", messageOf(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/cases/${c.id}/shares/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Access removed"); refresh(); },
    onError: (e) => toast.error("Could not remove access", messageOf(e)),
  });
  if (!c.permissions.share) return null;
  const candidates = (users.data ?? []).filter((u) => u.id !== c.owner_id && !(shares.data ?? []).some((s) => s.user_id === u.id) && u.is_active);
  return (
    <Card>
      <CardContent>
        <h2 className="text-lg">Sharing</h2>
        <p className="mt-1 text-sm text-stone-700">People who can open this case besides you ({user?.full_name}).</p>
        {shares.isLoading ? <Loading rows={2} /> : (
          <ul className="mt-3 divide-y divide-stone-200">
            {(shares.data ?? []).length === 0 && <li className="py-2 text-sm text-stone-700">Not shared with anyone.</li>}
            {(shares.data ?? []).map((s) => (
              <li key={s.user_id} className="flex items-center justify-between gap-3 py-2">
                <span><span className="font-semibold text-navy">{s.full_name}</span> <span className="text-sm text-stone-700">{s.email}</span> <Badge>{s.permission}</Badge></span>
                <Button variant="ghost" size="sm" aria-label={`Remove ${s.full_name}`} onClick={() => remove.mutate(s.user_id)}><Trash2 className="h-4 w-4" aria-hidden="true" /></Button>
              </li>
            ))}
          </ul>
        )}
        {users.isSuccess ? (
          <form className="mt-4 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (pick) add.mutate(); }}>
            <div>
              <label htmlFor="share-user" className="mb-1 block text-xs font-semibold">Share with</label>
              <select id="share-user" value={pick} onChange={(e) => setPick(e.target.value)} className="h-10 rounded-lg border border-stone-300 bg-white px-2 text-sm text-navy">
                <option value="">Choose a person</option>
                {candidates.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.role})</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="share-perm" className="mb-1 block text-xs font-semibold">Access</label>
              <select id="share-perm" value={permission} onChange={(e) => setPermission(e.target.value as "read" | "write")} className="h-10 rounded-lg border border-stone-300 bg-white px-2 text-sm text-navy">
                <option value="read">Read</option>
                <option value="write">Edit</option>
              </select>
            </div>
            <Button type="submit" size="sm" disabled={!pick || add.isPending}>Share</Button>
          </form>
        ) : (
          <p className="mt-3 text-sm text-stone-600">Only administrators can look up people to share with.</p>
        )}
      </CardContent>
    </Card>
  );
}

export function OverviewTab({ c, report, hasChart }: { c: CaseItem; report?: Report; hasChart: boolean }) {
  return (
    <div className="space-y-6">
      <Card>
        <CardContent>
          <h2 className="text-lg">Case summary</h2>
          <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Fact label="Status"><StatusChip status={c.status} /></Fact>
            <Fact label="Pipeline stage">{c.stage ? statusLabel(c.stage) : "Not run yet"}</Fact>
            <Fact label="Priority date">{c.priority_date ?? "Not set"}</Fact>
            <Fact label="Jurisdiction">{c.jurisdiction}</Fact>
            <Fact label="Language model mode">{c.llm_mode.replace("_", " ")}</Fact>
            <Fact label="Retention">{c.retention_days ? `${c.retention_days} days` : "Default"}</Fact>
            <Fact label="Created">{fmt(c.created_at)}</Fact>
            <Fact label="Last updated">{fmt(c.updated_at)}</Fact>
            <Fact label="Report">{report ? `Version ${report.version}, ${statusLabel(report.state)}` : hasChart ? "Not generated yet" : "Not available until the first run"}</Fact>
          </dl>
        </CardContent>
      </Card>
      {report?.content.executive_summary && (
        <Card>
          <CardContent>
            <h2 className="text-lg">Executive summary</h2>
            <p className="mt-2 whitespace-pre-line text-base text-stone-700">{report.content.executive_summary}</p>
            <p className="mt-2 text-sm text-stone-600">{report.content.generated_by}</p>
          </CardContent>
        </Card>
      )}
      <SharingPanel c={c} />
    </div>
  );
}

export function DisclosureTab({ caseId }: { caseId: string }) {
  const d = useDisclosure(caseId);
  if (d.isLoading) return <Loading rows={5} />;
  if (d.isError) return <ErrorState error={d.error} onRetry={() => d.refetch()} />;
  const x = d.data!;
  return (
    <Card>
      <CardContent className="space-y-5">
        <div>
          <h2 className="text-lg">{x.title}</h2>
          {x.technical_field && <p className="mt-1 text-sm text-stone-700">Field: {x.technical_field}</p>}
        </div>
        <section aria-labelledby="d-problem"><h3 id="d-problem" className="text-base">Problem</h3><p className="mt-1 whitespace-pre-line text-stone-700">{x.problem || "Not provided"}</p></section>
        <section aria-labelledby="d-solution"><h3 id="d-solution" className="text-base">Solution</h3><p className="mt-1 whitespace-pre-line text-stone-700">{x.solution || "Not provided"}</p></section>
        <section aria-labelledby="d-elements">
          <h3 id="d-elements" className="text-base">Elements</h3>
          {x.elements.length === 0 ? <p className="mt-1 text-stone-700">No elements yet.</p> : (
            <ol className="mt-2 space-y-2">
              {x.elements.map((e, i) => (
                <li key={e.id} className="flex gap-3 rounded-lg bg-stone-50 p-3"><span className="w-8 font-mono text-sm font-semibold text-teal-700">E{i + 1}</span><span className="text-navy">{e.text}</span></li>
              ))}
            </ol>
          )}
        </section>
      </CardContent>
    </Card>
  );
}

export function ResultsTab({ caseId, ran }: { caseId: string; ran: boolean }) {
  const r = useResults(caseId, ran);
  if (!ran) return <EmptyState title="No search results yet" text="Run the analysis to search the corpus for prior art." />;
  if (r.isLoading) return <Loading rows={5} />;
  if (r.isError) return <ErrorState error={r.error} onRetry={() => r.refetch()} />;
  const items = r.data?.results ?? [];
  if (!items.length) return <EmptyState title="Nothing found" text="The search returned no references for this disclosure." />;
  const top = Math.max(...items.map((i) => i.score), 0.0001);
  return (
    <div className="space-y-3">
      <p className="text-sm text-stone-700">{items.length} references ranked by relevance. Those marked &ldquo;In chart&rdquo; were compared element by element.</p>
      <ol className="space-y-3">
        {items.map((it) => (
          <li key={it.patent_id}>
            <Card className={it.excluded ? "opacity-60" : ""}>
              <CardContent className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm text-stone-600">#{it.rank}</p>
                    <h3 className="text-base"><span className="font-mono text-teal-800">{it.patent_id}</span> {it.title}</h3>
                    <p className="mt-1 text-sm text-stone-700">{[it.assignee, it.publication_date].filter(Boolean).join(" · ") || "No assignee or date on record"}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {it.source && <Badge>{it.source === "PV_GRANT" ? "Granted" : it.source === "HUPD_APP" ? "Application" : it.source}</Badge>}
                    {it.in_chart && <Badge tone="teal">In chart</Badge>}
                    {it.excluded && <Badge tone="neutral">Excluded</Badge>}
                    {it.url && <a href={it.url} target="_blank" rel="noopener noreferrer" className="text-teal-700" aria-label={`Open ${it.patent_id} in a new tab`}><ExternalLink className="h-4 w-4" aria-hidden="true" /></a>}
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <div className="h-2 flex-1 rounded-full bg-stone-200" role="meter" aria-label={`Relevance score ${it.score.toFixed(2)}`} aria-valuemin={0} aria-valuemax={1} aria-valuenow={Math.min(1, it.score / top)}>
                    <div className="h-2 rounded-full bg-teal-600" style={{ width: `${Math.min(100, (it.score / top) * 100)}%` }} />
                  </div>
                  <span className="w-12 text-right font-mono text-xs text-stone-700">{it.score.toFixed(2)}</span>
                </div>
                {it.cpc_subclasses.length > 0 && (
                  <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="CPC subclasses">
                    {it.cpc_subclasses.map((cpc) => <li key={cpc}><Badge tone="navy" className="font-mono">{cpc}</Badge></li>)}
                  </ul>
                )}
              </CardContent>
            </Card>
          </li>
        ))}
      </ol>
    </div>
  );
}

const EVENT_LABEL: Record<string, string> = {
  submitted: "Submitted for review",
  approved: "Approved",
  changes_requested: "Changes requested",
  override: "Cell overridden",
  cell_override: "Cell overridden",
  commented: "Comment",
};

export function ActivityTab({ caseId }: { caseId: string }) {
  const events = useReviewEvents(caseId);
  if (events.isLoading) return <Loading rows={4} />;
  if (events.isError) return <ErrorState error={events.error} onRetry={() => events.refetch()} />;
  const list = [...(events.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  if (!list.length) return <EmptyState title="No activity yet" text="Reviews, overrides and approvals appear here." />;
  return (
    <ol className="relative space-y-4 border-l-2 border-stone-200 pl-6" aria-label="Activity timeline">
      {list.map((e) => (
        <li key={e.id} className="relative">
          <span className="absolute -left-[31px] top-1.5 h-3 w-3 rounded-full bg-teal-600 ring-4 ring-white" aria-hidden="true" />
          <p className="font-semibold text-navy">{EVENT_LABEL[e.event_type] ?? statusLabel(e.event_type)}</p>
          <p className="text-sm text-stone-600"><time dateTime={e.created_at}>{fmt(e.created_at)}</time></p>
          {e.comment && <p className="mt-1 whitespace-pre-line rounded-lg bg-stone-50 p-3 text-stone-700">{e.comment}</p>}
        </li>
      ))}
    </ol>
  );
}
