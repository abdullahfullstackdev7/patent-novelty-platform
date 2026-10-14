import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { AppRoutes } from "@/App";

export const PLANS = [
  { code: "starter", name: "Starter", monthly_price: "490.00", included_reports: 15, overage_price: "40.00", seats: 3, extra_seat_price: "49.00" },
  { code: "professional", name: "Professional", monthly_price: "1490.00", included_reports: 50, overage_price: "30.00", seats: 10, extra_seat_price: "59.00" },
  { code: "enterprise", name: "Enterprise", monthly_price: "4900.00", included_reports: 200, overage_price: "20.00", seats: 50, extra_seat_price: "0.00" },
];
export const STATS = { patents: 12345, chunks: 98765, sources: ["HUPD_APP", "PV_GRANT"] };

type Handler = (init?: RequestInit) => { status?: number; body: unknown };

/** Replaces fetch with canned answers keyed by "METHOD path". Unknown requests fail the test. */
export function mockApi(overrides: Record<string, Handler> = {}) {
  const calls: { method: string; path: string; body?: unknown }[] = [];
  const handlers: Record<string, Handler> = {
    "GET /api/v1/public/plans": () => ({ body: PLANS }),
    "GET /api/v1/public/stats": () => ({ body: STATS }),
    ...overrides,
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    calls.push({ method, path: url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const handler = handlers[key];
    if (!handler) throw new Error(`Unexpected request: ${key}`);
    const { status = 200, body } = handler(init);
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export async function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  // lazy routes show a loading status until their chunk resolves
  await waitFor(() => expect(screen.queryByRole("status", { name: "Loading page" })).toBeNull());
  return view;
}
