import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/app/client";
import { CoverageChip, EmptyState, ErrorState, Loading, RiskBadge, messageOf, useToast } from "@/app/components/feedback";
import { keys, useChart, useRisk } from "@/app/hooks";
import { buildGrid } from "@/app/logic";
import type { CaseItem, Report } from "@/app/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError } from "@/lib/api";

const LEVEL_COLOR: Record<string, string> = { high: "#B42318", medium: "#B54708", low: "#067647" };

/** Half-circle gauge. The score is 0 to 100. */
export function RiskGauge({ score, level }: { score: number | null; level: string | null }) {
  const value = Math.max(0, Math.min(100, score ?? 0));
  const angle = Math.PI * (1 - value / 100);
  const x = 100 + 80 * Math.cos(angle);
  const y = 100 - 80 * Math.sin(angle);
  const color = LEVEL_COLOR[level ?? ""] ?? "#78746C";
  return (
    <figure className="text-center" aria-label={`Risk score ${score ?? "not available"} out of 100`}>
      <svg viewBox="0 0 200 120" className="mx-auto w-56" role="img" aria-hidden="true">
        <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="#E7E4DE" strokeWidth="16" strokeLinecap="round" />
        {score !== null && <path d={`M20 100 A80 80 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`} fill="none" stroke={color} strokeWidth="16" strokeLinecap="round" />}
      </svg>
      <figcaption className="-mt-10">
        <span className="block text-3xl font-semibold text-navy">{score ?? "n/a"}</span>
        <span className="text-sm text-stone-700">out of 100</span>
      </figcaption>
    </figure>
  );
}

function Heatmap({ caseId }: { caseId: string }) {
  const chart = useChart(caseId);
  if (chart.isLoading) return <Loading rows={3} />;
  if (!chart.data || !chart.data.references.length) return null;
  const grid = buildGrid(chart.data);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[28rem] border-collapse text-left text-sm">
        <caption className="sr-only">Coverage of each element by each reference</caption>
        <thead>
          <tr>
            <th scope="col" className="p-2 font-semibold">Element</th>
            {chart.data.references.map((r) => <th key={r} scope="col" className="p-2 font-mono font-semibold">{r}</th>)}
          </tr>
        </thead>
        <tbody>
          {chart.data.elements.map((e) => (
            <tr key={e.id} className="border-t border-stone-200">
              <th scope="row" className="p-2 font-normal"><span className="font-mono font-semibold text-teal-800">{e.id}</span> <span className="text-stone-700">{e.text.length > 60 ? `${e.text.slice(0, 57)}...` : e.text}</span></th>
              {chart.data!.references.map((r) => <td key={r} className="p-2"><CoverageChip status={grid.get(e.id)?.get(r)?.status ?? null} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RiskReportTab({ c, report, ran }: { c: CaseItem; report: UseQueryResult<Report>; ran: boolean }) {
  const risk = useRisk(c.id, ran);
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [summary, setSummary] = useState("");
  const content = report.data?.content;
  useEffect(() => setSummary(content?.executive_summary ?? ""), [content?.executive_summary]);

  const save = useMutation({
    mutationFn: () => api<Report>(`/cases/${c.id}/report`, { method: "PUT", body: { content: { ...content, executive_summary: summary } } }),
    onSuccess: () => {
      toast.success("New report version saved");
      setEditing(false);
      qc.invalidateQueries({ queryKey: keys.report(c.id) });
    },
    onError: (e) => toast.error("Could not save the report", messageOf(e)),
  });

  if (!ran) return <EmptyState title="No risk report yet" text="The risk assessment is produced when the analysis finishes." />;
  if (risk.isLoading || report.isLoading) return <Loading rows={5} />;
  if (risk.isError && !(risk.error instanceof ApiError && risk.error.status === 404)) return <ErrorState error={risk.error} onRetry={() => risk.refetch()} />;
  const r = risk.data;
  const canEdit = c.permissions.edit && report.data && !["approved", "in_review"].includes(report.data.state);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <Card>
          <CardContent className="text-center">
            <h2 className="mb-2 text-lg">Overall risk</h2>
            <RiskGauge score={r?.score ?? null} level={r?.level ?? null} />
            <div className="mt-3"><RiskBadge level={r?.level ?? null} /></div>
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <h2 className="text-lg">How this was assessed</h2>
            <p className="mt-2 text-base text-stone-700">{r?.basis ?? "The assessment is not available yet."}</p>
            {r?.anticipation_reference && <p className="mt-2 text-base"><strong>Closest single reference:</strong> <span className="font-mono">{r.anticipation_reference}</span></p>}
            {r && r.uncovered_elements.length > 0 && <p className="mt-2 text-base"><strong>Not found in any reference:</strong> {r.uncovered_elements.join(", ")}</p>}
            {r && r.combination.length > 0 && <p className="mt-2 text-base"><strong>Combination that covers the claim:</strong> <span className="font-mono">{r.combination.join(" + ")}</span></p>}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent>
          <h2 className="mb-3 text-lg">Coverage heatmap</h2>
          <Heatmap caseId={c.id} />
        </CardContent>
      </Card>

      {report.data ? (
        <Card>
          <CardContent>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg">Executive summary <span className="text-sm font-normal text-stone-600">(version {report.data.version})</span></h2>
              {canEdit && !editing && <Button variant="outline" size="sm" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" aria-hidden="true" /> Edit</Button>}
            </div>
            {editing ? (
              <div className="mt-3">
                <label htmlFor="summary" className="sr-only">Executive summary</label>
                <textarea id="summary" rows={10} value={summary} onChange={(e) => setSummary(e.target.value)} className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-base text-navy" />
                <div className="mt-3 flex gap-2">
                  <Button disabled={save.isPending || !summary.trim() || summary === content?.executive_summary} onClick={() => save.mutate()}>Save as new version</Button>
                  <Button variant="outline" onClick={() => { setEditing(false); setSummary(content?.executive_summary ?? ""); }}>Cancel</Button>
                </div>
              </div>
            ) : (
              <>
                <p className="mt-3 whitespace-pre-line text-base text-stone-700">{content?.executive_summary}</p>
                <p className="mt-2 text-sm text-stone-600">{content?.generated_by}</p>
              </>
            )}
          </CardContent>
        </Card>
      ) : (
        <EmptyState title="No report generated yet" text="Use Generate report in the page header to create the first version." />
      )}

      {content?.limitations && (
        <Card>
          <CardContent>
            <h2 className="text-lg">Limitations</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-base text-stone-700">{content.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            {content.disclaimer && <p className="mt-3 text-sm text-stone-600">{content.disclaimer}</p>}
          </CardContent>
        </Card>
      )}

      {report.data && report.data.versions.length > 0 && (
        <Card>
          <CardContent>
            <h2 className="text-lg">Version history</h2>
            <ol className="mt-2 divide-y divide-stone-200">
              {[...report.data.versions].sort((a, b) => b.version - a.version).map((v) => (
                <li key={v.version} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span className="font-semibold text-navy">Version {v.version}{v.version === report.data!.version ? " (current)" : ""}</span>
                  <span className="text-stone-700">{new Date(v.created_at).toLocaleString()}{v.approved_at ? ` · approved ${new Date(v.approved_at).toLocaleDateString()}` : ""}</span>
                  <span className="font-mono text-xs text-stone-600">{v.content_hash.slice(0, 12)}</span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
