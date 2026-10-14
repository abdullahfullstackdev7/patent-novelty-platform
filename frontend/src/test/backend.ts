// A small in-memory stand-in for the API, used by the application tests. It mirrors the response shapes in app/types.ts.
import { vi } from "vitest";

import type { Cell, CaseItem, Chart, Report, User } from "@/app/types";

export const ME: User = {
  id: "u-attorney",
  email: "attorney@example.com",
  full_name: "Alex Attorney",
  role: "attorney",
  client_id: null,
  is_active: true,
  totp_enabled: false,
  last_login_at: null,
  created_at: "2026-01-01T00:00:00Z",
};
export const ADMIN: User = { ...ME, id: "u-admin", email: "admin@example.com", full_name: "Ada Admin", role: "admin" };
export const VIEWER: User = { ...ME, id: "u-viewer", email: "viewer@example.com", full_name: "Vic Viewer", role: "viewer" };

const perms = (edit = true) => ({ edit, delete: edit, share: edit, review: false });
const makeCase = (n: number, patch: Partial<CaseItem> = {}): CaseItem => ({
  id: `c${n}`,
  title: `Case ${n}`,
  status: "approved",
  stage: "done",
  risk_level: "low",
  risk_score: 20 + n,
  priority_date: null,
  jurisdiction: "US",
  llm_mode: "local_only",
  confidential: true,
  retention_days: null,
  owner_id: ME.id,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T14:00:00Z",
  permissions: perms(),
  ...patch,
});

export const CASES: CaseItem[] = [
  makeCase(1, { title: "Battery thermal controller", status: "ready", risk_level: "high", risk_score: 82, updated_at: "2026-10-10T10:00:00Z" }),
  makeCase(2, { title: "Adaptive cooling manifold", status: "in_review", risk_level: "medium", risk_score: 55, permissions: { ...perms(), review: true } }),
  makeCase(3, { title: "Draft sensor idea", status: "draft", risk_level: null, risk_score: null, stage: null }),
  ...Array.from({ length: 10 }, (_, i) => makeCase(i + 4, { owner_id: "someone-else" })),
];

const cell = (id: string, element: string, patent: string, status: Cell["status"], excerpt: string | null, extra: Partial<Cell> = {}): Cell => ({
  id,
  element,
  patent_id: patent,
  status,
  confidence: 0.9,
  passage_id: excerpt ? `${patent}:p1` : null,
  excerpt,
  rationale: excerpt ? "The passage describes the same feature." : null,
  method: "local",
  char_start: excerpt ? 4 : null,
  char_end: excerpt ? 10 : null,
  overridden: false,
  original: null,
  override_reason: null,
  ...extra,
});

export const CHART: Chart = {
  chart_status: "done",
  references: ["US100A1", "US200B2"],
  elements: [
    { id: "E1", position: 1, text: "a temperature sensor on the cell", source: "user" },
    { id: "E2", position: 2, text: "a controller reducing charge current", source: "user" },
    { id: "E3", position: 3, text: "a coolant loop along the housing", source: "user" },
  ],
  cells: [
    cell("k1", "E1", "US100A1", "disclosed", "The thermistor senses the cell temperature."),
    cell("k2", "E2", "US100A1", "partial", "Charging may be limited at high heat."),
    cell("k3", "E3", "US100A1", "not_found", null),
    cell("k4", "E1", "US200B2", "not_found", null),
    cell("k5", "E2", "US200B2", "not_found", null),
    cell("k6", "E3", "US200B2", "not_found", null),
  ],
};

export const REPORT: Report = {
  state: "draft",
  version: 1,
  content_hash: "abcdef0123456789",
  content: {
    title: "Battery thermal controller",
    generated_by: "Machine-generated summary",
    executive_summary: "One reference discloses most elements.",
    limitations: ["The search covers only the indexed corpus."],
    disclaimer: "Not legal advice.",
  },
  versions: [{ version: 1, content_hash: "abcdef0123456789", created_at: "2026-10-01T10:00:00Z", approved_at: null }],
  approval: null,
};

type Handler = (args: { url: URL; init?: RequestInit; match: RegExpMatchArray; body: any }) => { status?: number; body?: unknown; stream?: string[] } | void;

export interface Backend {
  calls: { method: string; path: string; body: unknown }[];
  on: (method: string, pattern: RegExp, handler: Handler) => void;
  state: { chart: Chart; cases: CaseItem[]; report: Report };
}

/** Installs a fetch stub. Routes can be replaced per test with `on`; later registrations win. */
export function installBackend(user: User | null = ME): Backend {
  const calls: Backend["calls"] = [];
  const state = { chart: structuredClone(CHART), cases: structuredClone(CASES), report: structuredClone(REPORT) };
  const routes: { method: string; pattern: RegExp; handler: Handler }[] = [];
  const on: Backend["on"] = (method, pattern, handler) => routes.unshift({ method, pattern, handler });

  on("POST", /^\/auth\/refresh$/, () => (user ? { body: { access_token: "tok", token_type: "bearer", expires_in: 900, user } } : { status: 401, body: { detail: "No session" } }));
  on("POST", /^\/auth\/login$/, ({ body }) =>
    body.password === "right" ? { body: { access_token: "tok", token_type: "bearer", expires_in: 900, user: user ?? ME } } : { status: 401, body: { detail: "Invalid credentials" } },
  );
  on("POST", /^\/auth\/logout$/, () => ({ status: 204 }));
  on("GET", /^\/cases$/, () => ({ body: { items: state.cases, total: state.cases.length } }));
  on("GET", /^\/cases\/(c\d+)$/, ({ match }) => {
    const found = state.cases.find((c) => c.id === match[1]);
    return found ? { body: found } : { status: 404, body: { detail: "Case not found" } };
  });
  on("DELETE", /^\/cases\/(c\d+)$/, ({ match }) => {
    state.cases = state.cases.filter((c) => c.id !== match[1]);
    return { status: 204 };
  });
  on("GET", /^\/cases\/c\d+\/disclosure$/, () => ({
    body: { title: "Battery thermal controller", technical_field: "Batteries", problem: "Cells overheat.", solution: "A sensor and a controller.", elements: CHART.elements, content_hash: "h" },
  }));
  on("GET", /^\/cases\/c\d+\/results$/, () => ({
    body: {
      run_id: "r1",
      suggested_cpc: [],
      results: [
        { rank: 1, patent_id: "US100A1", title: "Adaptive battery thermal controller", source: "HUPD_APP", assignee: "Acme Corp", publication_date: "2024-03-01", cpc_subclasses: ["H01M"], url: null, score: 0.91, fused_score: 0.5, rerank_score: 0.9, matched_chunk_ids: [], excluded: false, in_chart: true },
        { rank: 2, patent_id: "US200B2", title: "Cooling manifold", source: "PV_GRANT", assignee: null, publication_date: null, cpc_subclasses: ["F28D"], url: null, score: 0.42, fused_score: 0.3, rerank_score: 0.4, matched_chunk_ids: [], excluded: false, in_chart: true },
      ],
    },
  }));
  on("GET", /^\/cases\/c\d+\/chart$/, () => ({ body: state.chart }));
  on("PATCH", /^\/chart\/cells\/(k\d+)$/, ({ match, body }) => {
    const target = state.chart.cells.find((c) => c.id === match[1])!;
    target.original = { status: target.status };
    target.status = body.status;
    target.overridden = true;
    target.override_reason = body.reason;
    return { body: target };
  });
  on("GET", /^\/cases\/c\d+\/risk$/, () => ({
    body: { level: "high", label: "High", score: 82, basis: "US100A1 discloses two of three elements.", anticipation_reference: "US100A1", combination: [], shared_subclasses: [], uncovered_elements: ["E3"], per_element: [], coverage: {}, references: [] },
  }));
  on("GET", /^\/cases\/c\d+\/report$/, () => ({ body: state.report }));
  on("PUT", /^\/cases\/c\d+\/report$/, ({ body }) => {
    state.report = { ...state.report, version: state.report.version + 1, content: body.content };
    return { body: state.report };
  });
  on("POST", /^\/cases\/c\d+\/review\/(submit|approve|request-changes)$/, ({ match }) => {
    state.report.state = match[1] === "submit" ? "in_review" : match[1] === "approve" ? "approved" : "changes_requested";
    return { body: state.report };
  });
  on("GET", /^\/cases\/c\d+\/review$/, () => ({
    body: [
      { id: 1, event_type: "submitted", user_id: ME.id, cell_id: null, comment: "Ready for you", created_at: "2026-10-01T10:00:00Z" },
      { id: 2, event_type: "approved", user_id: "u2", cell_id: null, comment: null, created_at: "2026-10-02T10:00:00Z" },
    ],
  }));
  on("GET", /^\/cases\/c\d+\/shares$/, () => ({ body: [] }));
  on("GET", /^\/llm\/mode$/, () => ({ body: { mode: "auto", providers_configured: { groq: false, gemini: false }, llm_available: false } }));
  on("GET", /^\/users$/, () => (user?.role === "admin" ? { body: [ADMIN, ME, VIEWER] } : { status: 403, body: { detail: "Forbidden" } }));
  on("GET", /^\/public\/stats$/, () => ({ body: { patents: 500, chunks: 20171, sources: ["HUPD_APP"] } }));
  on("GET", /^\/public\/plans$/, () => ({ body: [] }));

  const stub = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, "http://localhost");
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" && init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, body });
    for (const r of routes) {
      const match = path.match(r.pattern);
      if (r.method === method && match) {
        const out = r.handler({ url, init, match, body }) ?? {};
        if (out.stream) {
          const enc = new TextEncoder();
          const stream = new ReadableStream({
            start(controller) {
              out.stream!.forEach((s) => controller.enqueue(enc.encode(s)));
              controller.close();
            },
          });
          return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
        }
        return new Response(out.status === 204 ? null : JSON.stringify(out.body ?? {}), { status: out.status ?? 200, headers: { "Content-Type": "application/json" } });
      }
    }
    throw new Error(`Unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", stub);
  return { calls, on, state };
}

export const sse = (snapshot: Record<string, unknown>) => `event: status\ndata: ${JSON.stringify(snapshot)}\n\n`;
