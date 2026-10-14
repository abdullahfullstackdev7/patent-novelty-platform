import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileCheck2, MessageSquareWarning, Play, Send } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, downloadFile } from "@/app/client";
import { ActivityTab, DisclosureTab, OverviewTab, ResultsTab } from "@/app/case/tabs";
import { ChartViewer } from "@/app/case/ChartViewer";
import { RiskReportTab } from "@/app/case/RiskReport";
import { ErrorState, Loading, RiskBadge, StatusChip, messageOf, useToast } from "@/app/components/feedback";
import { PageHeader } from "@/app/components/Shell";
import { keys, useCase, useInvalidateCase, useReport } from "@/app/hooks";
import type { Report } from "@/app/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlay";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api";
import { Seo } from "@/lib/seo";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "disclosure", label: "Disclosure" },
  { id: "results", label: "Search results" },
  { id: "chart", label: "Claim chart" },
  { id: "risk", label: "Risk report" },
  { id: "activity", label: "Activity" },
];

type ReviewAction = "submit" | "approve" | "request-changes";
const COPY: Record<ReviewAction, { title: string; text: string; button: string; required: boolean }> = {
  submit: { title: "Submit for review", text: "The case becomes read-only for editing while a reviewer checks the chart and report.", button: "Submit for review", required: false },
  approve: { title: "Approve this report", text: "Approval records your name, the time and the exact report version. It cannot be undone, but a new version needs a new approval.", button: "Approve report", required: false },
  "request-changes": { title: "Request changes", text: "Tell the author what must change before this can be approved.", button: "Request changes", required: true },
};

export default function CaseWorkspace() {
  const { caseId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const invalidate = useInvalidateCase(caseId);
  const caseQuery = useCase(caseId);
  const c = caseQuery.data;
  const hasChart = !!c && !["draft", "running"].includes(c.status);
  const report = useReport(caseId, hasChart);
  const [action, setAction] = useState<ReviewAction | null>(null);
  const [comment, setComment] = useState("");
  const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab")! : "overview";

  const review = useMutation({
    mutationFn: (a: ReviewAction) => api<Report>(`/cases/${caseId}/review/${a}`, { method: "POST", body: { comment: comment.trim() || null } }),
    onSuccess: (_r, a) => {
      toast.success(a === "approve" ? "Report approved" : a === "submit" ? "Submitted for review" : "Changes requested");
      setAction(null);
      setComment("");
      invalidate();
    },
    onError: (e) => toast.error("That action was not allowed", messageOf(e)),
  });

  const rerun = useMutation({
    mutationFn: () => api(`/cases/${caseId}/run`, { method: "POST", body: { references: 3, force_search: false } }),
    onSuccess: () => navigate(`/app/cases/${caseId}/run`),
    onError: (e) => toast.error("Could not start the run", messageOf(e)),
  });

  const makeReport = useMutation({
    mutationFn: () => api<Report>(`/cases/${caseId}/report`, { method: "POST" }),
    onSuccess: () => {
      toast.success("Report generated");
      qc.invalidateQueries({ queryKey: keys.report(caseId) });
      invalidate();
    },
    onError: (e) => toast.error("Could not generate the report", messageOf(e)),
  });

  async function exportPdf() {
    try {
      await downloadFile(`/cases/${caseId}/report/export`, `report-${caseId}.pdf`, { format: "pdf" });
      toast.success("PDF exported");
    } catch (e) {
      toast.error(e instanceof ApiError && e.status === 503 ? "PDF rendering is not available on this server" : "Export failed", messageOf(e));
    }
  }

  if (caseQuery.isLoading) return <Loading label="Loading case" />;
  if (caseQuery.isError || !c) return <ErrorState error={caseQuery.error} onRetry={() => caseQuery.refetch()} />;

  const reportState = report.data?.state;
  const canSubmit = c.permissions.edit && report.data && ["draft", "changes_requested"].includes(reportState ?? "");
  const canDecide = c.permissions.review && reportState === "in_review";

  return (
    <>
      <Seo title={c.title} description="Case workspace." path={`/app/cases/${c.id}`} />
      <PageHeader
        crumbs={[{ label: "Dashboard", to: "/app" }, { label: "Cases", to: "/app/cases" }, { label: c.title }]}
        title={c.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <StatusChip status={c.status} /> <RiskBadge level={c.risk_level} />
            {c.confidential && <span className="text-sm text-stone-700">Confidential</span>}
          </span>
        }
        actions={
          <>
            {c.status === "running" && <Button asChild><Link to={`/app/cases/${c.id}/run`}>View progress</Link></Button>}
            {c.permissions.edit && c.status !== "running" && c.status !== "in_review" && (
              <Button variant={hasChart ? "outline" : "primary"} disabled={rerun.isPending} onClick={() => (c.status === "draft" ? navigate(`/app/cases/new?case=${c.id}`) : rerun.mutate())}>
                <Play className="h-4 w-4" aria-hidden="true" /> {c.status === "draft" ? "Continue setup" : "Run again"}
              </Button>
            )}
            {hasChart && !report.data && c.permissions.edit && (
              <Button variant="outline" disabled={makeReport.isPending} onClick={() => makeReport.mutate()}><FileCheck2 className="h-4 w-4" aria-hidden="true" /> Generate report</Button>
            )}
            {canSubmit && <Button variant="outline" onClick={() => setAction("submit")}><Send className="h-4 w-4" aria-hidden="true" /> Submit for review</Button>}
            {canDecide && (
              <>
                <Button variant="outline" onClick={() => setAction("request-changes")}><MessageSquareWarning className="h-4 w-4" aria-hidden="true" /> Request changes</Button>
                <Button onClick={() => setAction("approve")}><FileCheck2 className="h-4 w-4" aria-hidden="true" /> Approve</Button>
              </>
            )}
            {report.data && <Button variant="outline" onClick={exportPdf}><Download className="h-4 w-4" aria-hidden="true" /> Export PDF</Button>}
          </>
        }
      />

      <Tabs value={tab} onValueChange={(v) => setParams({ tab: v }, { replace: true })}>
        <TabsList aria-label="Case sections">
          {TABS.map((t) => <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>)}
        </TabsList>
        <TabsContent value="overview"><OverviewTab c={c} report={report.data} hasChart={hasChart} /></TabsContent>
        <TabsContent value="disclosure"><DisclosureTab caseId={c.id} /></TabsContent>
        <TabsContent value="results"><ResultsTab caseId={c.id} ran={hasChart} /></TabsContent>
        <TabsContent value="chart"><ChartViewer caseId={c.id} canEdit={c.permissions.edit && c.status !== "in_review" && reportState !== "approved"} ran={hasChart} /></TabsContent>
        <TabsContent value="risk"><RiskReportTab c={c} report={report} ran={hasChart} /></TabsContent>
        <TabsContent value="activity"><ActivityTab caseId={c.id} /></TabsContent>
      </Tabs>

      <Dialog open={!!action} onOpenChange={(o) => !o && setAction(null)}>
        <DialogContent>
          {action && (
            <>
              <DialogTitle className="text-lg font-semibold text-navy">{COPY[action].title}</DialogTitle>
              <DialogDescription className="mt-2 text-base text-stone-700">{COPY[action].text}</DialogDescription>
              <label htmlFor="review-comment" className="mt-4 block text-sm font-semibold">Comment{COPY[action].required ? "" : " (optional)"}</label>
              <textarea id="review-comment" rows={4} value={comment} onChange={(e) => setComment(e.target.value)} className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-base text-navy" />
              <div className="mt-5 flex justify-end gap-2">
                <Button variant="outline" onClick={() => setAction(null)}>Cancel</Button>
                <Button disabled={review.isPending || (COPY[action].required && !comment.trim())} onClick={() => review.mutate(action)}>{COPY[action].button}</Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
