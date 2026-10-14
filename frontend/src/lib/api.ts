// Plain fetch helpers. Request validation (zod) lives in forms.ts so the first page does not download it.

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, parse: (data: unknown) => T, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, detail || "Request failed");
  }
  return parse(await response.json());
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;

export interface Plan {
  code: string;
  name: string;
  monthly_price: number;
  included_reports: number;
  overage_price: number;
  seats: number;
  extra_seat_price: number;
}

function parsePlan(raw: unknown): Plan {
  if (!isRecord(raw) || typeof raw.code !== "string" || typeof raw.name !== "string") throw new Error("Unexpected plan shape");
  // The API serialises money as strings to avoid float drift; the site only displays them.
  return {
    code: raw.code,
    name: raw.name,
    monthly_price: Number(raw.monthly_price),
    included_reports: Number(raw.included_reports),
    overage_price: Number(raw.overage_price),
    seats: Number(raw.seats),
    extra_seat_price: Number(raw.extra_seat_price),
  };
}

export interface CorpusStats {
  patents: number;
  chunks: number;
  sources: string[];
}

function parseStats(raw: unknown): CorpusStats {
  if (!isRecord(raw) || typeof raw.patents !== "number") throw new Error("Unexpected stats shape");
  return { patents: raw.patents, chunks: Number(raw.chunks), sources: Array.isArray(raw.sources) ? raw.sources.map(String) : [] };
}

export const fetchPlans = () =>
  request("/public/plans", (d) => {
    if (!Array.isArray(d)) throw new Error("Unexpected plans shape");
    return d.map(parsePlan);
  });
export const fetchStats = () => request("/public/stats", parseStats);

export interface ContactPayload {
  name: string;
  email: string;
  organization?: string;
  topic: "demo" | "sales" | "support" | "other";
  message: string;
  website?: string;
}

export const sendContact = (input: ContactPayload) =>
  request("/public/contact", (d) => d as { received: boolean }, {
    method: "POST",
    body: JSON.stringify({ ...input, organization: input.organization || null }),
  });

export const login = (input: { email: string; password: string }) =>
  request("/auth/login", (d) => d as { access_token: string }, {
    method: "POST",
    body: JSON.stringify(input),
    credentials: "include",
  });
