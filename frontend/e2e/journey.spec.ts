import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

// Full user journey in a real browser: log in, create a case, run it, read the chart, override a cell,
// submit, approve and export. The backend is simulated in this file so the run needs no database or models.

const USER = { id: "u1", email: "attorney@example.com", full_name: "Alex Attorney", role: "attorney", client_id: null, is_active: true, totp_enabled: false, last_login_at: null, created_at: "2026-01-01T00:00:00Z" };
const ELEMENTS = [
  { id: "E1", position: 1, text: "a temperature sensor on the cell", source: "llm" },
  { id: "E2", position: 2, text: "a controller reducing charge current", source: "llm" },
];

function cell(id: string, element: string, patent: string, status: string, excerpt: string | null) {
  return { id, element, patent_id: patent, status, confidence: 0.9, passage_id: excerpt ? `${patent}:p1` : null, excerpt, rationale: excerpt ? "Same feature." : null, method: "local", char_start: null, char_end: null, overridden: false, original: null, override_reason: null };
}

async function mockApi(page: Page, seeded = false) {
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

test("public website to approved report", async ({ page }) => {
  const state = await mockApi(page);

  // The public site's Log in link reaches the login page.
  await page.goto("/");
  await page.getByRole("banner").getByRole("link", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/login$/);

  // Wrong password, then the right one.
  await page.getByLabel("Email").fill("attorney@example.com");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("The email or password is incorrect.")).toBeVisible();
  await page.getByLabel("Password").fill("correct horse");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Alex" })).toBeVisible();
  await expect(page.getByText("No cases yet")).toBeVisible();

  // The access token is never written to browser storage.
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(stored).not.toContain("tok");

  // Create the case.
  await page.getByRole("link", { name: "New case" }).first().click();
  await page.getByLabel("Title").fill("Heat sink");
  await page.getByLabel("Problem addressed").fill("Processors run too hot under sustained load.");
  await page.getByLabel("Solution and key features").fill("A fin array with a fan that spins up on demand.");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await page.getByRole("button", { name: "Extract from disclosure" }).click();
  await expect(page.getByLabel("Element 2", { exact: true })).toHaveValue("a controller reducing charge current");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Language model mode for this case").selectOption("local_only");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Nothing will leave this server")).toBeVisible();

  // Run and watch progress.
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page.getByText("The analysis is complete.")).toBeVisible();
  await expect(page.getByText("2,400")).toBeVisible();

  // Read the chart with the keyboard, then override a cell with a reason.
  await page.getByRole("link", { name: "Open the claim chart" }).click();
  await expect(page.getByRole("heading", { name: /US100A1/ })).toBeVisible();
  await expect(page.locator("blockquote")).toContainText("A thermistor senses cell temperature.");
  await page.locator("#el-btn-E1").focus();
  await page.keyboard.press("j");
  await expect(page.locator("#el-btn-E2")).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("2");
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Reason (required)").fill("The controller is described in the background section.");
  await dialog.getByRole("button", { name: "Save override" }).click();
  await expect(page.getByText(/Reviewer reason: The controller is described/)).toBeVisible();

  // Accessibility of the signature screen.
  const axe = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
  expect(axe.violations.map((v) => v.id)).toEqual([]);

  // Report, review, approval and export.
  await page.getByRole("tab", { name: "Risk report" }).click();
  await expect(page.getByRole("figure", { name: "Risk score 80 out of 100" })).toBeVisible();
  await page.getByRole("button", { name: "Submit for review" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Submit for review" }).click();
  await expect(page.getByText("Submitted for review")).toBeVisible();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText(/cannot be undone/)).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Approve report" }).click();
  await expect(page.getByText("Report approved")).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PDF" }).click();
  expect((await download).suggestedFilename()).toBe("report-c1.pdf");

  // A reload keeps the session through the refresh cookie, and logging out ends it.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Heat sink" })).toBeVisible();
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/login$/);
  expect(state.log).toContain("PATCH /chart/cells/k2");
});

test("the claim chart fits a phone screen without sideways scrolling", async ({ page }) => {
  await mockApi(page, true);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/login");
  await page.getByLabel("Email").fill("attorney@example.com");
  await page.getByLabel("Password").fill("correct horse");
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("heading", { name: /Welcome/ }).waitFor();
  await page.goto("/app/cases/c1?tab=chart");
  await expect(page.getByRole("heading", { name: /US100A1/ })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
