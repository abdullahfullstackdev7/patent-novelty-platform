import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, streamProgress } from "@/app/client";
import { ErrorState, messageOf, useToast } from "@/app/components/feedback";
import { PageHeader } from "@/app/components/Shell";
import { useCase } from "@/app/hooks";
import { formatElapsed, isFinalJob, stageStates } from "@/app/logic";
import type { ProgressSnapshot } from "@/app/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Seo } from "@/lib/seo";
import { cn } from "@/lib/utils";

export default function RunProgress() {
  const { caseId = "" } = useParams();
  const caseQuery = useCase(caseId);
  const qc = useQueryClient();
  const toast = useToast();
  const [snapshot, setSnapshot] = useState<ProgressSnapshot | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const started = useRef(Date.now());
  const done = snapshot ? isFinalJob(snapshot.status) : false;

  useEffect(() => {
    const controller = new AbortController();
    streamProgress(caseId, setSnapshot, controller.signal).catch((e) => {
      if (!controller.signal.aborted) setStreamError(messageOf(e));
    });
    return () => controller.abort();
  }, [caseId]);

  useEffect(() => {
    if (done) {
      qc.invalidateQueries({ queryKey: ["case", caseId] });
      qc.invalidateQueries({ queryKey: ["cases"] });
      return;
    }
    const timer = setInterval(() => setElapsed((Date.now() - started.current) / 1000), 1000);
    return () => clearInterval(timer);
  }, [done, caseId, qc]);

  const stages = stageStates(snapshot?.stage ?? null, snapshot?.status ?? "queued");
  const failed = snapshot?.status === "failed";
  const succeeded = snapshot?.status === "succeeded" || snapshot?.stage === "done";

  async function retry() {
    try {
      await api(`/cases/${caseId}/run`, { method: "POST", body: { references: 3, force_search: false } });
      window.location.reload();
    } catch (e) {
      toast.error("Could not restart the run", messageOf(e));
    }
  }

  return (
    <>
      <Seo title="Run progress" description="Live progress of the analysis." path={`/app/cases/${caseId}/run`} />
      <PageHeader
        crumbs={[{ label: "Dashboard", to: "/app" }, { label: "Cases", to: "/app/cases" }, { label: caseQuery.data?.title ?? "Case", to: `/app/cases/${caseId}` }, { label: "Run" }]}
        title="Analysis in progress"
      />
      {streamError && <ErrorState error={new Error(streamError)} />}
      <Card>
        <CardContent className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-3" aria-label="Run statistics">
            <div className="rounded-lg bg-stone-50 p-4"><p className="text-xs font-semibold uppercase text-stone-600">Elapsed</p><p className="text-xl font-semibold text-navy" aria-live="off">{formatElapsed(elapsed)}</p></div>
            <div className="rounded-lg bg-stone-50 p-4"><p className="text-xs font-semibold uppercase text-stone-600">Tokens used</p><p className="text-xl font-semibold text-navy">{(snapshot?.tokens_used ?? 0).toLocaleString()}</p></div>
            <div className="rounded-lg bg-stone-50 p-4"><p className="text-xs font-semibold uppercase text-stone-600">Status</p><p className="text-xl font-semibold capitalize text-navy">{snapshot?.status ?? "connecting"}</p></div>
          </div>

          <ol className="space-y-3" aria-label="Pipeline stages" aria-live="polite">
            {stages.map((s) => (
              <li key={s.id} className={cn("flex items-center gap-3 text-base", s.state === "pending" ? "text-stone-600" : "text-navy")} aria-current={s.state === "active" ? "step" : undefined}>
                {s.state === "done" ? <CheckCircle2 className="h-5 w-5 text-risk-low" aria-hidden="true" /> : s.state === "active" ? <Loader2 className="h-5 w-5 animate-spin text-teal-700" aria-hidden="true" /> : s.state === "failed" ? <XCircle className="h-5 w-5 text-risk-high" aria-hidden="true" /> : <Circle className="h-5 w-5 text-stone-400" aria-hidden="true" />}
                <span className={s.state === "active" ? "font-semibold" : ""}>{s.label}</span>
                <span className="sr-only">{s.state}</span>
              </li>
            ))}
          </ol>

          {failed && (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-risk-high">
              <p className="font-semibold">The run failed</p>
              <p className="text-base">{snapshot?.error ?? "An unexpected error stopped the analysis."}</p>
              <Button variant="outline" size="sm" className="mt-3 bg-white" onClick={retry}>Try again</Button>
            </div>
          )}
          {succeeded && (
            <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-green-200 bg-green-50 p-4 text-risk-low">
              <p className="font-semibold">The analysis is complete.</p>
              <Button asChild><Link to={`/app/cases/${caseId}?tab=chart`}>Open the claim chart</Link></Button>
            </div>
          )}
          {!done && <p className="text-sm text-stone-600">You can leave this page. The run continues on the server, and the case shows its status on the dashboard.</p>}
        </CardContent>
      </Card>
    </>
  );
}
