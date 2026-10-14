import { AlertTriangle, CheckCircle2, CircleDashed, Inbox, WifiOff, XCircle, MinusCircle } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { statusLabel, STATUS_META } from "@/app/logic";
import type { CellStatus } from "@/app/types";
import { Button } from "@/components/ui/button";
import { Badge, Skeleton } from "@/components/ui/card";
import { Toast, ToastProvider, ToastViewport } from "@/components/ui/overlay";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---- toasts ------------------------------------------------------------------------------------------------

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  tone: "success" | "error";
}

const ToastContext = createContext<{ success: (title: string, description?: string) => void; error: (title: string, description?: string) => void } | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast needs ToastHost");
  return ctx;
}

export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((tone: ToastItem["tone"], title: string, description?: string) => {
    setItems((current) => [...current.slice(-3), { id: Date.now() + Math.random(), title, description, tone }]);
  }, []);
  const value = {
    success: (t: string, d?: string) => push("success", t, d),
    error: (t: string, d?: string) => push("error", t, d),
  };
  return (
    <ToastContext.Provider value={value}>
      <ToastProvider duration={5000} label="Notifications">
        {children}
        {items.map((item) => (
          <Toast
            key={item.id}
            title={item.title}
            description={item.description}
            tone={item.tone}
            onOpenChange={(open) => !open && setItems((c) => c.filter((x) => x.id !== item.id))}
          />
        ))}
        <ToastViewport />
      </ToastProvider>
    </ToastContext.Provider>
  );
}

export const messageOf = (error: unknown) => (error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong");

// ---- page states ----------------------------------------------------------------------------------------------

export function Loading({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} aria-busy="true" className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const status = error instanceof ApiError ? error.status : 0;
  const text = status === 404 ? "We could not find that item, or you do not have access to it." : status === 403 ? "You do not have permission to see this." : messageOf(error);
  return (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-risk-high">
      <p className="flex items-center gap-2 font-semibold">
        <AlertTriangle className="h-5 w-5" aria-hidden="true" /> Something went wrong
      </p>
      <p className="mt-1 text-base">{text}</p>
      {onRetry && status !== 404 && status !== 403 && (
        <Button variant="outline" size="sm" className="mt-3 bg-white" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, text, action, icon: Icon = Inbox }: { title: string; text: string; action?: ReactNode; icon?: typeof Inbox }) {
  return (
    <div className="rounded-2xl border border-dashed border-stone-300 px-6 py-12 text-center">
      <Icon className="mx-auto h-9 w-9 text-stone-400" aria-hidden="true" />
      <h2 className="mt-3 text-lg">{title}</h2>
      <p className="mx-auto mt-1 max-w-md text-base text-stone-700">{text}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/** Shown on every screen when the browser reports no connection. */
export function OfflineBanner() {
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  if (online) return null;
  return (
    <div role="alert" className="flex items-center gap-2 bg-amber-100 px-4 py-2 text-sm font-medium text-risk-medium">
      <WifiOff className="h-4 w-4" aria-hidden="true" /> You are offline. Changes cannot be saved until the connection returns.
    </div>
  );
}

// ---- chips ---------------------------------------------------------------------------------------------------------

const STATUS_TONE: Record<string, "neutral" | "teal" | "high" | "medium" | "low" | "navy"> = {
  draft: "neutral",
  running: "teal",
  ready: "navy",
  in_review: "medium",
  approved: "low",
  changes_requested: "high",
  failed: "high",
};

export function StatusChip({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{statusLabel(status)}</Badge>;
}

export function RiskBadge({ level }: { level: string | null }) {
  if (!level) return <span className="text-stone-600">Not assessed</span>;
  const tone = level === "high" ? "high" : level === "medium" ? "medium" : "low";
  return <Badge tone={tone}>{level[0].toUpperCase() + level.slice(1)} risk</Badge>;
}

const ICONS = { disclosed: CheckCircle2, partial: MinusCircle, not_found: XCircle } as const;

/** Coverage status as icon plus text plus colour, so it never relies on colour alone. */
export function CoverageChip({ status, className }: { status: CellStatus | null; className?: string }) {
  if (!status) {
    return (
      <Badge className={className}>
        <CircleDashed className="h-3.5 w-3.5" aria-hidden="true" /> No data
      </Badge>
    );
  }
  const Icon = ICONS[status];
  const meta = STATUS_META[status];
  return (
    <Badge tone={meta.tone} className={cn(className)}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" /> {meta.label}
    </Badge>
  );
}
