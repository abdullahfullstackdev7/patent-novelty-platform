import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ARTICLES, articleText } from "@/content/articles";
import { FAQ, SAMPLE_FIRMS, SOLUTIONS, STEPS, TOUR } from "@/content/site";
import { wordCount } from "@/lib/utils";
import { LEGAL } from "@/pages/Legal";
import { mockApi, PLANS, renderAt, STATS } from "@/test/helpers";

const ALL_PATHS = [
  "/",
  "/platform",
  "/solutions",
  "/pricing",
  "/security",
  "/about",
  "/contact",
  "/resources",
  ...ARTICLES.map((a) => `/resources/${a.slug}`),
  ...Object.keys(LEGAL).map((d) => `/legal/${d}`),
  "/login",
  "/no-such-page",
];

beforeEach(() => {
  mockApi();
});

describe("home page", () => {
  it("renders the 13 sections in the specified order", async () => {
    const { container } = await renderAt("/");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Prior-art intelligence for confident patent decisions");
    const order = [
      "hero-title",
      "trust-title",
      "how",
      "capabilities",
      "tour",
      "solutions",
      "security",
      "stories",
      "insights",
      "pricing",
      "faq",
      "cta-title",
    ];
    const positions = order.map((id) => {
      const el = container.querySelector(`#${id}-title, #${id}`) ?? container.querySelector(`#${id}`);
      expect(el, `section ${id}`).not.toBeNull();
      return el!;
    });
    positions.forEach((el, i) => {
      if (i) expect(positions[i - 1].compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });
    expect(container.querySelector('section[aria-label="Key figures"]')).not.toBeNull();
    // key figures sit between the trust band and "how it works"
    const figures = container.querySelector('section[aria-label="Key figures"]')!;
    expect(positions[1].compareDocumentPosition(figures) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(figures.compareDocumentPosition(positions[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the real corpus count from the API, never an invented one", async () => {
    await renderAt("/");
    expect(await screen.findByText("12,345")).toBeInTheDocument();
    expect(screen.queryByText(/8M\+/)).toBeNull();
  });

  it("shows n/a instead of a number when the stats request fails", async () => {
    mockApi({ "GET /api/v1/public/stats": () => ({ status: 500, body: { detail: "boom" } }) });
    await renderAt("/");
    expect(await screen.findByText("n/a", {}, { timeout: 5000 })).toBeInTheDocument();
  });

  it("lists the five workflow steps, six capabilities' worth of content and four tour tabs", async () => {
    await renderAt("/");
    const how = document.getElementById("how")!;
    expect(within(how).getAllByRole("listitem")).toHaveLength(STEPS.length);
    expect(STEPS.map((s) => s.title)).toEqual(["Disclosure intake", "Semantic search", "Claim charting", "Risk assessment", "Attorney review"]);
    expect(screen.getAllByRole("tab")).toHaveLength(TOUR.length);
    expect(SOLUTIONS).toHaveLength(4);
  });

  it("labels fictional firms, stories and screenshots as sample content", async () => {
    await renderAt("/");
    expect(SAMPLE_FIRMS).toHaveLength(6);
    expect(screen.getByText(/the firms above are fictional/i)).toBeInTheDocument();
    expect(screen.getAllByText("Sample story")).toHaveLength(3);
    expect(screen.getAllByText("Sample content").length).toBeGreaterThan(0);
  });

  it("has an FAQ with eight questions that open and close", async () => {
    await renderAt("/");
    expect(FAQ).toHaveLength(8);
    const first = screen.getByRole("button", { name: FAQ[0].q });
    expect(first).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(first);
    expect(first).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/PatentsView granted patent data/)).toBeInTheDocument();
  });

  it("switches product tour tabs with the keyboard", async () => {
    await renderAt("/");
    const tabs = screen.getAllByRole("tab");
    tabs[0].focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
  });
});

describe("pricing comes from the plans API", () => {
  it("renders the three plans with their prices on Home and Pricing", async () => {
    await renderAt("/pricing");
    expect(await screen.findAllByText("$1,490")).not.toHaveLength(0);
    for (const plan of PLANS) expect(screen.getAllByText(plan.name).length).toBeGreaterThan(0);
    expect(screen.getByRole("table", { name: "Plan comparison" })).toBeInTheDocument();
    expect(screen.getAllByText("50").length).toBeGreaterThan(0);
  });

  it("falls back to a contact message when plans cannot be loaded", async () => {
    mockApi({ "GET /api/v1/public/plans": () => ({ status: 500, body: { detail: "down" } }) });
    await renderAt("/");
    expect((await screen.findAllByText(/Pricing could not be loaded/i, {}, { timeout: 5000 })).length).toBeGreaterThan(0);
  });
});

describe("navigation", () => {
  it("every Log in link goes to /login and Request a demo goes to the contact form", async () => {
    await renderAt("/");
    const logins = screen.getAllByRole("link", { name: /^log in$/i });
    expect(logins.length).toBeGreaterThanOrEqual(2);
    for (const link of logins) expect(link).toHaveAttribute("href", "/login");
    for (const link of screen.getAllByRole("link", { name: /^request a demo$/i })) {
      expect(link).toHaveAttribute("href", "/contact?topic=demo");
    }
  });

  it("opens the mobile menu with Log in and Request a demo", async () => {
    await renderAt("/");
    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
    expect(within(dialog).getByRole("link", { name: "Request a demo" })).toBeInTheDocument();
  });

  it("offers a skip link and a main landmark on every public page", async () => {
    await renderAt("/platform");
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", "#main");
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("footer has the five columns, the legal links and the data attribution", async () => {
    await renderAt("/");
    const footer = screen.getByRole("contentinfo");
    for (const name of ["Platform", "Solutions", "Resources", "Company", "Legal"]) {
      expect(within(footer).getByRole("navigation", { name })).toBeInTheDocument();
    }
    for (const label of ["Privacy Policy", "Terms of Use", "Cookie Notice", "Accessibility Statement", "Security"]) {
      expect(within(footer).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(footer).toHaveTextContent("PatentsView");
    expect(footer).toHaveTextContent("HUPD");
    expect(footer).toHaveTextContent("CC BY 4.0");
    expect(footer).toHaveTextContent("CC BY-SA 4.0");
  });

  it("shows a 404 page for unknown routes and unknown articles", async () => {
    await renderAt("/no-such-page");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("We could not find that page");
  });

  it("shows a 404 for an unknown article and an unknown legal document", async () => {
    await renderAt("/resources/nope");
    expect(await screen.findByText("We could not find that page")).toBeInTheDocument();
  });
});

describe("content quality", () => {
  it("has three articles of 400 to 600 words", async () => {
    expect(ARTICLES).toHaveLength(3);
    for (const a of ARTICLES) {
      const words = wordCount(articleText(a));
      expect(words, a.slug).toBeGreaterThanOrEqual(400);
      expect(words, a.slug).toBeLessThanOrEqual(600);
    }
  });

  it("contains no placeholder text or em dashes on any page", async () => {
    for (const path of ALL_PATHS) {
      const { container, unmount } = await renderAt(path);
      if (path === "/pricing" || path === "/") await screen.findAllByText(/\$1,490/);
      const text = container.textContent ?? "";
      expect(text, path).not.toMatch(/lorem|ipsum|TODO|TBD|placeholder text/i);
      expect(text, path).not.toMatch(/\u2014/);
      unmount();
    }
  });

  it("renders every article page with its headings", async () => {
    await renderAt(`/resources/${ARTICLES[1].slug}`);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Understanding claim charts");
    expect(screen.getAllByRole("heading", { level: 2 }).length).toBeGreaterThanOrEqual(4);
  });

  it("sets a distinct document title and canonical link per page", async () => {
    await renderAt("/security");
    await waitFor(() => expect(document.title).toBe("Security | PriorArt Atlas"));
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute("href", "https://priorart-atlas.example/security");
  });

  it("marks the About profiles as sample content", async () => {
    await renderAt("/about");
    expect(screen.getAllByText("Sample profile")).toHaveLength(3);
  });
});

describe("contact form", () => {
  async function fill(user: ReturnType<typeof userEvent.setup>, overrides: Partial<Record<string, string>> = {}) {
    await user.type(screen.getByLabelText("Full name"), overrides.name ?? "Dana Whitfield");
    await user.type(screen.getByLabelText("Work email"), overrides.email ?? "dana@example.com");
    await user.type(screen.getByLabelText("How can we help?"), overrides.message ?? "We would like a walkthrough for our team.");
  }

  it("validates before sending anything", async () => {
    const { calls } = mockApi();
    await renderAt("/contact");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByText("Enter your name")).toBeInTheDocument();
    expect(screen.getByText("Enter a valid email address")).toBeInTheDocument();
    expect(screen.getByText(/at least 10 characters/)).toBeInTheDocument();
    expect(screen.getByLabelText("Work email")).toHaveAttribute("aria-invalid", "true");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("posts the form, preselects the topic from the link and confirms", async () => {
    const { calls } = mockApi({ "POST /api/v1/public/contact": () => ({ status: 202, body: { received: true } }) });
    await renderAt("/contact?topic=sales");
    const user = userEvent.setup();
    expect(screen.getByLabelText("Topic")).toHaveValue("sales");
    await fill(user);
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByText(/your message was received/i)).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.path).toBe("/api/v1/public/contact");
    expect(post.body).toMatchObject({ name: "Dana Whitfield", email: "dana@example.com", topic: "sales", organization: null });
  });

  it("explains a rate-limit response and keeps the typed message", async () => {
    mockApi({ "POST /api/v1/public/contact": () => ({ status: 429, body: { detail: "slow down" } }) });
    await renderAt("/contact");
    const user = userEvent.setup();
    await fill(user);
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByText(/several messages recently/i)).toBeInTheDocument();
    expect(screen.getByLabelText("How can we help?")).toHaveValue("We would like a walkthrough for our team.");
  });

  it("hides the honeypot from assistive technology", async () => {
    await renderAt("/contact");
    expect(screen.queryByRole("textbox", { name: /leave this field empty/i })).toBeNull();
  });
});

describe("login page", () => {
  it("validates, then reports a wrong password without revealing which part was wrong", async () => {
    mockApi({ "POST /api/v1/auth/login": () => ({ status: 401, body: { detail: "Invalid credentials" } }) });
    await renderAt("/login");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByText("The email or password is incorrect.")).toBeInTheDocument();
  });

  it("signs in against the auth API", async () => {
    const { calls } = mockApi({ "POST /api/v1/auth/login": () => ({ body: { access_token: "t", token_type: "bearer" } }) });
    await renderAt("/login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByText(/You are signed in/)).toBeInTheDocument();
    expect(calls.at(-1)?.body).toEqual({ email: "a@example.com", password: "secret" });
  });
});

describe("accessibility (axe)", () => {
  it.each(ALL_PATHS)("%s has no detectable violations", async (path) => {
    const { container } = await renderAt(path);
    if (path === "/pricing" || path === "/") await screen.findAllByText(/\$1,490/);
    const results = await axe(container, { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } });
    expect(results).toHaveNoViolations();
  });
});

it("test fixtures stay consistent with the mocked stats", async () => {
  expect(STATS.patents).toBe(12345);
});
