import { defineConfig } from "@playwright/test";

// The journey runs against the production build (served with scripts/serve-dist.mjs) in the system Chrome.
// The API is simulated in the browser by e2e/journey.spec.ts, so no backend, database or model is needed.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:4174", channel: "chrome", headless: true, acceptDownloads: true },
  webServer: {
    command: "node scripts/serve-dist.mjs 4174 http://localhost:9",
    url: "http://localhost:4174",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
