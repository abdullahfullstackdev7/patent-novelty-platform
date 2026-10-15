import type { Page, Route } from "@playwright/test";

const USER = { id: "u1", email: "attorney@example.com", full_name: "Alex Attorney", role: "attorney", client_id: null, is_active: true, totp_enabled: false, last_login_at: null, created_at: "2026-01-01T00:00:00Z" };
const ELEMENTS = [
  { id: "E1", position: 1, text: "a temperature sensor on the cell", source: "llm" },
  { id: "E2", position: 2, text: "a controller reducing charge current", source: "llm" },
];

function cell(id: string, element: string, patent: string, status: string, excerpt: string | null) {
  return { id, element, patent_id: patent, status, confidence: 0.9, passage_id: excerpt ? `${patent}:p1` : null, excerpt, rationale: excerpt ? "Same feature." : null, method: "local", char_start: null, char_end: null, overridden: false, original: null, override_reason: null };
}

export async function mockApi(page: Page, seeded = false) {
  const s = {
    signedIn: false,
    created: seeded,
    status: seeded ? "ready" : "draft",
    reportState: "draft",
    cells: [cell("k1", "E1", "US100A1", "disclosed", "A thermistor senses cell temperature."), cell("k2", "E2", "US100A1", "not_found", null)],
    log: [] as string[],
  };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  const caseBody = () => ({
    id: "c1", title: "Heat sink", status: s.status, stage: s.status === "ready" ? "done" : null, risk_level: s.status === "ready" ? "high" : null, risk_score: s.status === "ready" ? 80 : null,
    priority_date: null, jurisdiction: "US", llm_mode: "local_only", confidential: true, retention_days: null, owner_id: "u1",
    created_at: "2026-10-14T10:00:00Z", updated_at: "2026-10-14T11:00:00Z", permissions: { edit: s.reportState !== "approved", delete: true, share: false, review: s.reportState === "in_review" },
  });
  const report = () => ({ state: s.reportState, version: 1, content_hash: "abcdef012345", content: { generated_by: "Machine-generated summary", executive_summary: "One reference discloses most elements.", limitations: ["Only the indexed corpus was searched."], disclaimer: "Not legal advice." }, versions: [{ version: 1, content_hash: "abcdef012345", created_at: "2026-10-14T11:00:00Z", approved_at: null }], approval: null });

  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace("/api/v1", "");
    const method = req.method();
    s.log.push(`${method} ${path}`);
    const body = req.postData() ? JSON.parse(req.postData()!) : null;

    if (path === "/auth/refresh") return s.signedIn ? json(route, { access_token: "tok", token_type: "bearer", expires_in: 900, user: USER }) : json(route, { detail: "No session" }, 401);
    if (path === "/auth/login") {
      if (body.password !== "correct horse") return json(route, { detail: "Invalid credentials" }, 401);
      s.signedIn = true;
      return json(route, { access_token: "tok", token_type: "bearer", expires_in: 900, user: USER });
    }
    if (path === "/auth/logout") { s.signedIn = false; return route.fulfill({ status: 204 }); }
    if (path === "/public/stats") return json(route, { patents: 500, chunks: 20171, sources: ["HUPD_APP"] });
    if (path === "/public/plans") return json(route, []);
    if (path === "/llm/mode") return json(route, { mode: "local_only", providers_configured: { groq: false, gemini: false }, llm_available: false });
    if (path === "/cases" && method === "GET") return json(route, { items: s.created ? [caseBody()] : [], total: s.created ? 1 : 0 });
    if (path === "/cases" && method === "POST") { s.created = true; return json(route, caseBody(), 201); }
    if (path === "/cases/c1" && method === "GET") return json(route, caseBody());
    if (path === "/cases/c1" && method === "PATCH") return json(route, caseBody());
    if (path === "/cases/c1/disclosure" && method === "PUT") return json(route, { ...body, elements: ELEMENTS, content_hash: "h" });
    if (path === "/cases/c1/disclosure" && method === "GET") return json(route, { title: "Heat sink", technical_field: "", problem: "Processors run too hot.", solution: "A fin array with a fan.", elements: ELEMENTS, content_hash: "h" });
    if (path === "/cases/c1/disclosure/extract-elements") return json(route, { elements: ELEMENTS, source: "local", tokens: 0, provider: null, cache_hit: false, fallback_reason: null });
    if (path === "/cases/c1/run") { s.status = "running"; return json(route, { id: "j1", kind: "pipeline", status: "queued", attempts: 0, error: null }, 202); }
    if (path === "/cases/c1/progress") {
      const snap = (stage: string, status: string, tokens: number) => `event: status\ndata: ${JSON.stringify({ status, job_id: "j1", stage, case_status: status === "succeeded" ? "ready" : "running", attempts: 1, error: null, tokens_used: tokens, updated_at: "t" })}\n\n`;
      s.status = "ready";
      s.reportState = "draft";
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: snap("search", "running", 0) + snap("charting", "running", 800) + snap("done", "succeeded", 2400) });
    }
    if (path === "/cases/c1/results") return json(route, { run_id: "r", suggested_cpc: [], results: [{ rank: 1, patent_id: "US100A1", title: "Adaptive thermal controller", source: "HUPD_APP", assignee: "Acme", publication_date: "2024-01-01", cpc_subclasses: ["H01M"], url: null, score: 0.9, fused_score: 0.5, rerank_score: 0.8, matched_chunk_ids: [], excluded: false, in_chart: true }] });
    if (path === "/cases/c1/chart") return json(route, { chart_status: "done", elements: ELEMENTS, references: ["US100A1"], cells: s.cells });
    if (path === "/chart/cells/k2" && method === "PATCH") {
      s.cells[1] = { ...s.cells[1], status: body.status, overridden: true, override_reason: body.reason, original: { status: "not_found" } };
      return json(route, s.cells[1]);
    }
    if (path === "/cases/c1/risk") return json(route, { level: "high", label: "High", score: 80, basis: "One reference discloses most elements.", anticipation_reference: "US100A1", combination: [], shared_subclasses: [], uncovered_elements: [], per_element: [], coverage: {}, references: [] });
    if (path === "/cases/c1/report" && method === "GET") return s.status === "draft" ? json(route, { detail: "No report" }, 404) : json(route, report());
    if (path === "/cases/c1/report" && method === "POST") return json(route, report(), 201);
    if (path === "/cases/c1/review/submit") { s.reportState = "in_review"; s.status = "in_review"; return json(route, report()); }
    if (path === "/cases/c1/review/approve") { s.reportState = "approved"; s.status = "approved"; return json(route, report()); }
    if (path === "/cases/c1/review") return json(route, []);
    if (path === "/cases/c1/report/export") return route.fulfill({ status: 200, contentType: "application/pdf", body: "%PDF-1.4 sample", headers: { "Content-Disposition": 'attachment; filename="report.pdf"' } });
    return json(route, { detail: `Unmocked ${method} ${path}` }, 500);
  });
  return s;
}

