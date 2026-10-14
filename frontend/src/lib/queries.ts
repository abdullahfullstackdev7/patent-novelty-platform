import { useQuery } from "@tanstack/react-query";

import { fetchPlans, fetchStats } from "@/lib/api";

export const usePlans = () => useQuery({ queryKey: ["plans"], queryFn: fetchPlans, staleTime: 300_000, retry: 1 });
export const useStats = () => useQuery({ queryKey: ["stats"], queryFn: fetchStats, staleTime: 300_000, retry: 1 });
