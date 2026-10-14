import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { getAccessToken, setAccessToken } from "@/app/client";
import { ADMIN, ME, VIEWER, installBackend, sse } from "@/test/backend";
import { renderAt } from "@/test/helpers";

const signedIn = () => localStorage.setItem("priorart.session", "1");
const AXE = { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } };

beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  document.documentElement.classList.remove("dark");
});

describe("sign-in and guards", () => {
  it("sends anonymous visitors to the login page", async () => {
    installBackend(null);
    await renderAt("/app/cases");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("logs in, lands on the dashboard and keeps the token out of storage", async () => {
    installBackend(ME);
    await renderAt("/login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "attorney@example.com");
    await user.type(screen.getByLabelText("Password"), "right");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("heading", { name: /Welcome, Alex/ })).toBeInTheDocument();
    expect(getAccessToken()).toBe("tok");
    expect(JSON.stringify({ ...localStorage })).not.toContain("tok\"");
    expect(Object.values({ ...localStorage }).some((v) => v === "tok")).toBe(false);
    expect(Object.values({ ...sessionStorage }).some((v) => v === "tok")).toBe(false);
  });

  it("shows an error for a wrong password", async () => {
    installBackend(ME);
    await renderAt("/login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "attorney@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByText("The email or password is incorrect.")).toBeInTheDocument();
  });

  it("asks for the authenticator code when the server requires it, then signs in", async () => {
    const api = installBackend(ME);
    api.on("POST", /^\/auth\/login$/, ({ body }) =>
      !body.totp_code
        ? { status: 401, body: { detail: "A TOTP code is required" } }
        : { body: { access_token: "tok", token_type: "bearer", expires_in: 900, user: ME } },
    );
    await renderAt("/login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "attorney@example.com");
    await user.type(screen.getByLabelText("Password"), "right");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("heading", { name: "Two-step verification" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Authentication code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify and log in" }));
    expect(await screen.findByRole("heading", { name: /Welcome/ })).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === "/auth/login").at(-1)!.body).toMatchObject({ totp_code: "123456" });
  });

  it("explains the admin password reset flow", async () => {
    installBackend(null);
    await renderAt("/login");
    await userEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    expect(await screen.findByText(/issued by an administrator/i)).toBeInTheDocument();
  });

  it("restores the session silently through the refresh cookie", async () => {
    const api = installBackend(ME);
    signedIn();
    await renderAt("/app");
    expect(await screen.findByRole("heading", { name: /Welcome, Alex/ })).toBeInTheDocument();
    expect(api.calls[0].path).toBe("/auth/refresh");
  });

  it("does not probe the refresh endpoint on public pages", async () => {
    const api = installBackend(null);
    await renderAt("/pricing");
    expect(api.calls.some((c) => c.path === "/auth/refresh")).toBe(false);
  });

  it("retries once with a new token after a 401 and logs out when the refresh fails", async () => {
    const api = installBackend(ME);
    signedIn();
    let first = true;
    api.on("GET", /^\/cases$/, () => {
      if (first) {
        first = false;
        return { status: 401, body: { detail: "expired" } };
      }
      return { body: { items: [], total: 0 } };
    });
    await renderAt("/app");
    expect(await screen.findByText("No cases yet")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === "/auth/refresh")).toHaveLength(2);
  });

  it("hides admin areas from non-admins and blocks the routes", async () => {
    installBackend(VIEWER);
    signedIn();
    await renderAt("/app/admin");
    expect(await screen.findByText("You do not have access to this page")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Application" });
    expect(within(nav).queryByRole("link", { name: "Admin" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "New case" })).toBeNull();
  });

  it("logs out and returns to the login page", async () => {
    const api = installBackend(ME);
    signedIn();
    await renderAt("/app");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Account menu" }));
    await user.click(screen.getByRole("button", { name: "Log out" }));
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/auth/logout")).toBe(true);
    expect(localStorage.getItem("priorart.session")).toBeNull();
  });
});

describe("dashboard", () => {
  beforeEach(() => signedIn());

  it("shows the KPIs and the first page of cases", async () => {
    installBackend(ME);
    await renderAt("/app");
    const kpis = await screen.findByRole("region", { name: "Key figures" });
    expect(within(kpis).getByText("Open cases").nextElementSibling).toHaveTextContent("3");
    expect(within(kpis).getByText("Awaiting review").nextElementSibling).toHaveTextContent("1");
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(11); // header + 10 cases
  });

  it("filters by status, by title and by owner, and clears the filters", async () => {
    installBackend(ME);
    await renderAt("/app/cases");
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.selectOptions(screen.getByLabelText("Status"), "in_review");
    expect(screen.getByRole("link", { name: "Adaptive cooling manifold" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.type(screen.getByLabelText("Title"), "sensor");
    expect(screen.getAllByRole("row")).toHaveLength(2);
    await user.clear(screen.getByLabelText("Title"));
    await user.selectOptions(screen.getByLabelText("Owner"), "me");
    expect(screen.getAllByRole("row")).toHaveLength(4);
    await user.selectOptions(screen.getByLabelText("Status"), "failed");
    expect(await screen.findByText("No cases match these filters.")).toBeInTheDocument();
  });

  it("sorts by a column and pages through the list", async () => {
    installBackend(ME);
    await renderAt("/app/cases");
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Title" }));
    await user.click(screen.getByRole("button", { name: "Title" }));
    expect(screen.getByRole("columnheader", { name: "Title" })).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("Adaptive cooling manifold");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("prefills the title filter from the global search", async () => {
    installBackend(ME);
    await renderAt("/app/cases?q=thermal");
    await screen.findByRole("table");
    expect(screen.getByLabelText("Title")).toHaveValue("thermal");
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });

  it("deletes a case after confirmation and tells the user", async () => {
    const api = installBackend(ME);
    await renderAt("/app/cases");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete Draft sensor idea" }));
    await user.click(screen.getByRole("button", { name: "Delete case" }));
    expect(await screen.findByText("Case deleted")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "DELETE" && c.path === "/cases/c3")).toBe(true);
  });

  it("shows an error state with a retry and an empty state", async () => {
    const api = installBackend(ME);
    api.on("GET", /^\/cases$/, () => ({ status: 500, body: { detail: "database down" } }));
    await renderAt("/app");
    expect(await screen.findByText("database down")).toBeInTheDocument();
    api.on("GET", /^\/cases$/, () => ({ body: { items: [], total: 0 } }));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No cases yet")).toBeInTheDocument();
  });

  it("lists review and failure notifications in the bell menu", async () => {
    installBackend(ME);
    signedIn();
    const api = installBackend({ ...ME });
    api.state.cases[1].permissions.review = true;
    await renderAt("/app");
    await userEvent.click(await screen.findByRole("button", { name: /Notifications, 1 new/ }));
    expect(await screen.findByText("Waiting for your review")).toBeInTheDocument();
  });

  it("toggles the dark theme and remembers it", async () => {
    installBackend(ME);
    await renderAt("/app");
    await userEvent.click(await screen.findByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("priorart.theme")).toBe("dark");
  });
});

describe("claim chart viewer", () => {
  beforeEach(() => signedIn());

  async function openChart(user = ME, mutate?: (api: ReturnType<typeof installBackend>) => void) {
    const api = installBackend(user);
    mutate?.(api);
    await renderAt("/app/cases/c1?tab=chart");
    await screen.findByRole("heading", { name: /US100A1/ });
    return api;
  }

  it("shows elements with icon-plus-text status, the reference header and the verbatim excerpt", async () => {
    await openChart();
    const list = screen.getByRole("heading", { name: "Elements" }).parentElement!;
    expect(within(list).getByText("a temperature sensor on the cell")).toBeInTheDocument();
    expect(within(list).getAllByText("Disclosed").length).toBeGreaterThan(0);
    expect(screen.getByText("Adaptive battery thermal controller")).toBeInTheDocument();
    expect(screen.getByText(/Acme Corp/)).toBeInTheDocument();
    const quote = document.querySelector("blockquote")!;
    expect(quote.textContent).toBe("The thermistor senses the cell temperature.");
    expect(quote.querySelector("mark")!.textContent).toBe("thermi");
    expect(screen.getByText(/Covers 1 disclosed, 1 partial and 1 not found of 3 elements/)).toBeInTheDocument();
  });

  it("moves between elements with J and K", async () => {
    await openChart();
    const user = userEvent.setup();
    const current = () => document.querySelector('[aria-current="true"]')!.id;
    expect(current()).toBe("el-btn-E1");
    await user.keyboard("j");
    expect(current()).toBe("el-btn-E2");
    expect(screen.getByText("Charging may be limited at high heat.")).toBeInTheDocument();
    await user.keyboard("jj");
    expect(current()).toBe("el-btn-E3");
    await user.keyboard("k");
    expect(current()).toBe("el-btn-E2");
  });

  it("switches reference tabs", async () => {
    await openChart();
    await userEvent.click(screen.getByRole("tab", { name: "US200B2" }));
    expect(await screen.findByRole("heading", { name: /US200B2/ })).toBeInTheDocument();
    expect(screen.getByText("No passage in this reference matches this element.")).toBeInTheDocument();
  });

  it("filters to uncovered elements only", async () => {
    await openChart();
    await userEvent.click(screen.getByLabelText(/Show only uncovered elements \(1\)/));
    const buttons = document.querySelectorAll('[id^="el-btn-"]');
    expect([...buttons].map((b) => b.id)).toEqual(["el-btn-E3"]);
  });

  it("overrides a status with a reason through the keyboard shortcut and records it", async () => {
    const api = await openChart();
    const user = userEvent.setup();
    await user.keyboard("2");
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Save override" })).toBeDisabled(); // no reason yet, same status not allowed
    await user.type(within(dialog).getByLabelText("Reason (required)"), "Reads on partial support only");
    await user.click(within(dialog).getByRole("button", { name: "Save override" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ status: "partial", reason: "Reads on partial support only" });
    expect(await screen.findByText("Status updated")).toBeInTheDocument();
    expect(await screen.findByText(/Reviewer reason: Reads on partial support only/)).toBeInTheDocument();
  });

  it("does not offer overrides or shortcuts to read-only users", async () => {
    await openChart(ME, (api) => api.state.cases.forEach((c) => (c.permissions.edit = false)));
    expect(screen.queryByRole("button", { name: "Override status" })).toBeNull();
    await userEvent.keyboard("1");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens the passage in context drawer", async () => {
    await openChart();
    await userEvent.click(screen.getByRole("button", { name: "View passage in context" }));
    expect(await screen.findByRole("heading", { name: "Passage in US100A1" })).toBeInTheDocument();
  });

  it("explains the chart is not available before the first run", async () => {
    const api = installBackend(ME);
    await renderAt("/app/cases/c3?tab=chart");
    expect(await screen.findByText("No claim chart yet")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.endsWith("/chart"))).toBe(false);
  });

  it("shows a not-found state for a case the user cannot see", async () => {
    installBackend(ME);
    await renderAt("/app/cases/c999");
    expect(await screen.findByText(/could not find that item, or you do not have access/i)).toBeInTheDocument();
  });
});

describe("risk report and review flow", () => {
  beforeEach(() => signedIn());

  it("shows the gauge, heatmap, summary, limitations and versions", async () => {
    installBackend(ME);
    await renderAt("/app/cases/c1?tab=risk");
    expect(await screen.findByRole("figure", { name: "Risk score 82 out of 100" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Coverage of each element/ })).toBeInTheDocument();
    expect(screen.getByText("One reference discloses most elements.")).toBeInTheDocument();
    expect(screen.getByText("The search covers only the indexed corpus.")).toBeInTheDocument();
    expect(screen.getByText(/Version 1 \(current\)/)).toBeInTheDocument();
  });

  it("saves an edited summary as a new report version", async () => {
    const api = installBackend(ME);
    await renderAt("/app/cases/c1?tab=risk");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const box = screen.getByLabelText("Executive summary");
    await user.clear(box);
    await user.type(box, "Revised by the attorney.");
    await user.click(screen.getByRole("button", { name: "Save as new version" }));
    expect(await screen.findByText("New report version saved")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "PUT" && c.path.endsWith("/report"))!.body).toMatchObject({ content: { executive_summary: "Revised by the attorney." } });
  });

  it("submits for review with a comment", async () => {
    const api = installBackend(ME);
    await renderAt("/app/cases/c1");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Submit for review/ }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Comment/), "Please check element 3");
    await user.click(within(dialog).getByRole("button", { name: "Submit for review" }));
    expect(await screen.findByText("Submitted for review")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.endsWith("/review/submit"))!.body).toEqual({ comment: "Please check element 3" });
  });

  it("lets a reviewer approve only after confirming, and requires a comment to request changes", async () => {
    const api = installBackend(ME);
    api.state.report.state = "in_review";
    await renderAt("/app/cases/c2");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Request changes/ }));
    let dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Request changes" })).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: /^Approve$/ }));
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/cannot be undone/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Approve report" }));
    expect(await screen.findByText("Report approved")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.endsWith("/review/approve"))).toBe(true);
  });

  it("does not show approval buttons to people without review rights", async () => {
    const api = installBackend(ME);
    api.state.report.state = "in_review";
    await renderAt("/app/cases/c1");
    await screen.findByRole("heading", { name: "Battery thermal controller" });
    expect(screen.queryByRole("button", { name: /^Approve$/ })).toBeNull();
  });

  it("reports when PDF export is unavailable", async () => {
    const api = installBackend(ME);
    api.on("POST", /^\/cases\/c1\/report\/export$/, () => ({ status: 503, body: { detail: "PDF rendering is not available on this server" } }));
    await renderAt("/app/cases/c1");
    await userEvent.click(await screen.findByRole("button", { name: /Export PDF/ }));
    expect(await screen.findByText("PDF rendering is not available on this server", { selector: "[class*=font-semibold]" })).toBeInTheDocument();
  });

  it("shows the activity timeline newest first", async () => {
    installBackend(ME);
    await renderAt("/app/cases/c1?tab=activity");
    const timeline = await screen.findByRole("list", { name: "Activity timeline" });
    const items = within(timeline).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Approved");
    expect(items[1]).toHaveTextContent("Ready for you");
  });

  it("lists search results with score meters and in-chart badges", async () => {
    installBackend(ME);
    await renderAt("/app/cases/c1?tab=results");
    expect(await screen.findByText("Cooling manifold")).toBeInTheDocument();
    expect(screen.getAllByText("In chart")).toHaveLength(2);
    expect(screen.getByRole("meter", { name: "Relevance score 0.91" })).toBeInTheDocument();
    expect(screen.getByText("Application")).toBeInTheDocument();
  });
});

describe("run progress", () => {
  beforeEach(() => signedIn());

  it("follows the stream to completion and links to the chart", async () => {
    const api = installBackend(ME);
    api.on("GET", /^\/cases\/c1\/progress$/, () => ({
      stream: [
        sse({ status: "running", job_id: "j", stage: "search", case_status: "running", attempts: 1, error: null, tokens_used: 120, updated_at: "t" }),
        sse({ status: "succeeded", job_id: "j", stage: "done", case_status: "ready", attempts: 1, error: null, tokens_used: 4300, updated_at: "t" }),
      ],
    }));
    await renderAt("/app/cases/c1/run");
    expect(await screen.findByText("The analysis is complete.")).toBeInTheDocument();
    expect(screen.getByText("4,300")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the claim chart" })).toHaveAttribute("href", "/app/cases/c1?tab=chart");
  });

  it("shows the failure and offers a retry", async () => {
    const api = installBackend(ME);
    api.on("GET", /^\/cases\/c1\/progress$/, () => ({
      stream: [sse({ status: "failed", job_id: "j", stage: "charting", case_status: "failed", attempts: 3, error: "Provider unavailable", tokens_used: 10, updated_at: "t" })],
    }));
    await renderAt("/app/cases/c1/run");
    expect(await screen.findByText("Provider unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("new case wizard", () => {
  beforeEach(() => signedIn());

  it("validates the disclosure, creates the case, edits elements and starts the run", async () => {
    const api = installBackend(ME);
    api.on("POST", /^\/cases$/, () => ({ status: 201, body: { ...api.state.cases[2], id: "c99", title: "Heat sink" } }));
    api.on("PUT", /^\/cases\/c99\/disclosure$/, ({ body }) => ({ body: { ...body, elements: [], content_hash: "h" } }));
    api.on("POST", /^\/cases\/c99\/disclosure\/extract-elements$/, () => ({
      body: { elements: [{ id: "E1", position: 1, text: "a fin array; a fan", source: "llm" }], source: "llm", tokens: 100, provider: "groq", cache_hit: false, fallback_reason: null },
    }));
    api.on("PATCH", /^\/cases\/c99$/, () => ({ body: {} }));
    api.on("POST", /^\/cases\/c99\/run$/, () => ({ status: 202, body: { id: "j", kind: "pipeline", status: "queued", attempts: 0, error: null } }));
    api.on("GET", /^\/cases\/c99\/progress$/, () => ({ stream: [] }));
    api.on("GET", /^\/cases\/c99$/, () => ({ body: { ...api.state.cases[2], id: "c99", title: "Heat sink" } }));

    await renderAt("/app/cases/new");
    const user = userEvent.setup();
    await screen.findByLabelText("Title");
    expect(screen.getByText(/Disclosures are encrypted at rest/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(await screen.findByText("Enter a title")).toBeInTheDocument();
    expect(screen.getByText(/Describe the problem/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("Title"), "Heat sink");
    await user.type(screen.getByLabelText("Problem addressed"), "Processors run too hot under load.");
    await user.type(screen.getByLabelText("Solution and key features"), "A fin array with a fan that spins up on demand.");
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(await screen.findByRole("button", { name: "Extract from disclosure" })).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "POST" && c.path === "/cases")!.body).toEqual({ title: "Heat sink" });

    await user.click(screen.getByRole("button", { name: "Extract from disclosure" }));
    const first = await screen.findByLabelText("Element 1");
    expect(first).toHaveValue("a fin array; a fan");
    await user.click(screen.getByRole("button", { name: "Add element" }));
    await user.type(screen.getByLabelText("Element 2"), "a heat pipe");
    await user.click(screen.getByRole("button", { name: "Merge element 1 with the next" }));
    expect(screen.getByLabelText("Element 1")).toHaveValue("a fin array; a fan; a heat pipe");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByLabelText(/Priority date/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText(/Nothing will leave this server|Only the disclosure text needed/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "/cases/c99/run")).toBe(true));
    expect(api.calls.find((c) => c.path === "/cases/c99/run")!.body).toEqual({ references: 3, force_search: false });
    expect(await screen.findByRole("heading", { name: "Analysis in progress" })).toBeInTheDocument();
  });

  it("keeps the first-step draft in the browser until the case exists", async () => {
    installBackend(ME);
    await renderAt("/app/cases/new");
    await userEvent.type(await screen.findByLabelText("Title"), "Draft title");
    expect(JSON.parse(localStorage.getItem("priorart.newcase.draft")!).title).toBe("Draft title");
  });

  it("requires at least one element before moving on", async () => {
    const api = installBackend(ME);
    api.on("POST", /^\/cases$/, () => ({ status: 201, body: { ...api.state.cases[2], id: "c98" } }));
    api.on("PUT", /^\/cases\/c98\/disclosure$/, ({ body }) => ({ body }));
    await renderAt("/app/cases/new");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Title"), "T");
    await user.type(screen.getByLabelText("Problem addressed"), "x".repeat(25));
    await user.type(screen.getByLabelText("Solution and key features"), "y".repeat(25));
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    await screen.findByRole("button", { name: "Add element" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Add at least one element")).toBeInTheDocument();
  });
});

describe("administration", () => {
  beforeEach(() => signedIn());

  it("lists users, changes a role and creates a one-time reset link", async () => {
    const api = installBackend(ADMIN);
    api.on("PATCH", /^\/users\/u-viewer$/, ({ body }) => ({ body: { ...VIEWER, ...body } }));
    api.on("POST", /^\/users\/u-attorney\/reset-password$/, () => ({ body: { reset_token: "r".repeat(40), expires_at: "2026-10-20T00:00:00Z" } }));
    await renderAt("/app/admin");
    const user = userEvent.setup();
    expect(await screen.findByText("Vic Viewer")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Role for Vic Viewer"), "analyst");
    await waitFor(() => expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ role: "analyst" }));
    await user.click(screen.getByRole("button", { name: "Reset password for Alex Attorney" }));
    const dialog = await screen.findByRole("dialog");
    expect((within(dialog).getByLabelText("One-time link") as HTMLInputElement).value).toContain("/accept?token=");
    expect(screen.getByLabelText("Role for Ada Admin")).toBeDisabled(); // admins cannot demote themselves here
  });

  it("shows LLM quota meters and saves settings", async () => {
    const api = installBackend(ADMIN);
    const provider = (name: string) => ({
      name, model: `${name}-model`, configured: name === "groq",
      breaker: { state: "closed", failures: 0, retry_in_seconds: 0 },
      minute: { tokens_used: 100, tokens_limit: 8000, requests_used: 1, requests_limit: 30 },
      day: { tokens_used: 5000, tokens_limit: 100000, tokens_percent: 5, requests_used: 10, requests_limit: 1000, requests_percent: 1 },
    });
    api.on("GET", /^\/admin\/llm\/status$/, () => ({ body: { mode: "auto", providers: [provider("groq"), provider("gemini")] } }));
    api.on("GET", /^\/admin\/llm\/settings$/, () => ({ body: { mode: "auto", groq_model: "g1", gemini_model: "m1", defaults: { mode: "auto", groq_model: "g1", gemini_model: "m1" } } }));
    api.on("PUT", /^\/admin\/llm\/settings$/, () => ({ body: {} }));
    await renderAt("/app/admin");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Language models" }));
    expect((await screen.findAllByRole("meter", { name: "Tokens today" })).length).toBe(2);
    await user.selectOptions(screen.getByLabelText("Mode"), "local_only");
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByText("LLM settings saved")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "PUT")!.body).toMatchObject({ mode: "local_only", groq_model: "g1" });
  });

  it("shows the corpus status and the audit log", async () => {
    const api = installBackend(ADMIN);
    api.on("GET", /^\/admin\/audit$/, () => ({
      body: [{ id: 1, user_id: null, action: "auth.login", entity_type: "user", entity_id: "abcdef123456", ip_address: "10.0.0.1", detail: {}, created_at: "2026-10-01T10:00:00Z" }],
    }));
    await renderAt("/app/admin");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Corpus" }));
    expect(await screen.findByText("500")).toBeInTheDocument();
    expect(screen.getByText("HUPD applications")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Audit log" }));
    expect(await screen.findByText("auth.login")).toBeInTheDocument();
  });
});

describe("offline and accessibility", () => {
  beforeEach(() => signedIn());

  it("warns when the browser goes offline", async () => {
    installBackend(ME);
    await renderAt("/app");
    await screen.findByRole("heading", { name: /Welcome/ });
    window.dispatchEvent(new Event("offline"));
    expect(await screen.findByText(/You are offline/)).toBeInTheDocument();
  });

  it.each([
    ["dashboard", "/app", ME],
    ["case list", "/app/cases", ME],
    ["new case", "/app/cases/new", ME],
    ["case overview", "/app/cases/c1", ME],
    ["disclosure", "/app/cases/c1?tab=disclosure", ME],
    ["search results", "/app/cases/c1?tab=results", ME],
    ["claim chart", "/app/cases/c1?tab=chart", ME],
    ["risk report", "/app/cases/c1?tab=risk", ME],
    ["activity", "/app/cases/c1?tab=activity", ME],
    ["admin", "/app/admin", ADMIN],
    ["progress", "/app/cases/c1/run", ME],
  ] as const)("%s has no detectable accessibility violations", async (_name, path, who) => {
    const api = installBackend(who);
    api.on("GET", /^\/cases\/c1\/progress$/, () => ({ stream: [] }));
    const { container } = await renderAt(path);
    await waitFor(() => expect(container.querySelector('[role="status"][aria-busy="true"]')).toBeNull());
    await screen.findByRole("main");
    await new Promise((r) => setTimeout(r, 30));
    expect(await axe(container, AXE)).toHaveNoViolations();
  });

  it("login and accept pages have no detectable violations", async () => {
    installBackend(null);
    for (const path of ["/login", "/accept?token=" + "t".repeat(30)]) {
      const { container, unmount } = await renderAt(path);
      expect(await axe(container, AXE)).toHaveNoViolations();
      unmount();
    }
  });
});
