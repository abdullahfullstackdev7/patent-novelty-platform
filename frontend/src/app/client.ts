// Authenticated API client. The access token lives in this module's memory only (never in storage).
// A 401 triggers one silent refresh through the HttpOnly refresh cookie, then the request is retried.

import { ApiError } from "@/lib/api";
import type { ProgressSnapshot, TokenResponse } from "@/app/types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

let accessToken: string | null = null;
let refreshing: Promise<TokenResponse | null> | null = null;
let onSessionLost: (() => void) | null = null;

export const setAccessToken = (token: string | null) => {
  accessToken = token;
};
export const getAccessToken = () => accessToken;
export const setSessionLostHandler = (handler: (() => void) | null) => {
  onSessionLost = handler;
};

async function detailOf(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail) && body.detail[0]?.msg) return String(body.detail[0].msg);
  } catch {
    /* not JSON */
  }
  return response.statusText || "Request failed";
}

/** Exchanges the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<TokenResponse | null> {
  refreshing ??= (async () => {
    try {
      const response = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "include" });
      if (!response.ok) return null;
      const data = (await response.json()) as TokenResponse;
      accessToken = data.access_token;
      return data;
    } catch {
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  raw?: boolean;
}

function urlOf(path: string, query?: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function send(path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  return fetch(urlOf(path, opts.query), {
    method: opts.method ?? "GET",
    headers,
    credentials: "include",
    signal: opts.signal,
    body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
  });
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  let response = await send(path, opts);
  if (response.status === 401 && !path.startsWith("/auth/")) {
    const renewed = await refreshSession();
    if (!renewed) {
      setAccessToken(null);
      onSessionLost?.();
      throw new ApiError(401, "Your session has expired. Please log in again.");
    }
    response = await send(path, opts);
  }
  if (!response.ok) throw new ApiError(response.status, await detailOf(response));
  if (opts.raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Reads the Server-Sent Events stream of a run. EventSource cannot send an Authorization header, so fetch is used. */
export async function streamProgress(
  caseId: string,
  onSnapshot: (snapshot: ProgressSnapshot) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await api<Response>(`/cases/${caseId}/progress`, { raw: true, signal });
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const data = block.split("\n").find((l) => l.startsWith("data: "));
      if (data) onSnapshot(JSON.parse(data.slice(6)) as ProgressSnapshot);
    }
  }
}

export async function downloadFile(path: string, filename: string, query?: RequestOptions["query"]): Promise<void> {
  const response = await api<Response>(path, { method: "POST", raw: true, query });
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
