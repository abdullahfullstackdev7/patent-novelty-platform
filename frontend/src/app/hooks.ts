import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/app/client";
import type {
  AuditEntry,
  Cell,
  CaseItem,
  CaseList,
  Chart,
  Disclosure,
  LlmModeInfo,
  LlmSettings,
  LlmStatus,
  Report,
  Results,
  ReviewEvent,
  Risk,
  User,
} from "@/app/types";
import { fetchStats } from "@/lib/api";

export const keys = {
  cases: ["cases"] as const,
  case: (id: string) => ["case", id] as const,
  disclosure: (id: string) => ["case", id, "disclosure"] as const,
  results: (id: string) => ["case", id, "results"] as const,
  chart: (id: string) => ["case", id, "chart"] as const,
  risk: (id: string) => ["case", id, "risk"] as const,
  report: (id: string) => ["case", id, "report"] as const,
  review: (id: string) => ["case", id, "review"] as const,
};

export const useCases = () => useQuery({ queryKey: keys.cases, queryFn: () => api<CaseList>("/cases", { query: { limit: 200 } }) });
export const useCase = (id: string) => useQuery({ queryKey: keys.case(id), queryFn: () => api<CaseItem>(`/cases/${id}`) });
export const useDisclosure = (id: string) => useQuery({ queryKey: keys.disclosure(id), queryFn: () => api<Disclosure>(`/cases/${id}/disclosure`) });
export const useResults = (id: string, enabled = true) => useQuery({ queryKey: keys.results(id), queryFn: () => api<Results>(`/cases/${id}/results`), enabled });
export const useChart = (id: string, enabled = true) => useQuery({ queryKey: keys.chart(id), queryFn: () => api<Chart>(`/cases/${id}/chart`), enabled });
export const useRisk = (id: string, enabled = true) => useQuery({ queryKey: keys.risk(id), queryFn: () => api<Risk>(`/cases/${id}/risk`), enabled, retry: false });
export const useReport = (id: string, enabled = true) => useQuery({ queryKey: keys.report(id), queryFn: () => api<Report>(`/cases/${id}/report`), enabled, retry: false });
export const useReviewEvents = (id: string) => useQuery({ queryKey: keys.review(id), queryFn: () => api<ReviewEvent[]>(`/cases/${id}/review`) });
export const useLlmMode = () => useQuery({ queryKey: ["llm-mode"], queryFn: () => api<LlmModeInfo>("/llm/mode"), staleTime: 60_000 });
export const useUsers = () => useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
export const useAudit = (params: { action?: string; limit: number; offset: number }) =>
  useQuery({ queryKey: ["audit", params], queryFn: () => api<AuditEntry[]>("/admin/audit", { query: params }) });
export const useLlmStatus = () => useQuery({ queryKey: ["llm-status"], queryFn: () => api<LlmStatus>("/admin/llm/status"), refetchInterval: 15_000 });
export const useLlmSettings = () => useQuery({ queryKey: ["llm-settings"], queryFn: () => api<LlmSettings>("/admin/llm/settings") });
export const useCorpus = () => useQuery({ queryKey: ["corpus"], queryFn: fetchStats, staleTime: 60_000 });

export function useOverrideCell(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { cellId: string; status: Cell["status"]; reason: string }) =>
      api<Cell>(`/chart/cells/${v.cellId}`, { method: "PATCH", body: { status: v.status, reason: v.reason } }),
    onSuccess: () => {
      for (const k of [keys.chart(caseId), keys.risk(caseId), keys.case(caseId), keys.review(caseId)]) qc.invalidateQueries({ queryKey: k });
    },
  });
}

export function useInvalidateCase(caseId: string) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["case", caseId] }).then(() => qc.invalidateQueries({ queryKey: keys.cases }));
}
