// Runs Lighthouse against the production preview and prints the four category scores.
// Usage: npm run build && (npm run preview &) && npm run lighthouse -- http://localhost:4173/
import { spawnSync } from "node:child_process";

const url = process.argv[2] ?? "http://localhost:4173/";
const result = spawnSync(
  "npx",
  ["--yes", "lighthouse@12.2.1", url, "--quiet", "--output=json", "--output-path=stdout",
   "--chrome-flags=--headless=new --no-sandbox", "--only-categories=performance,accessibility,seo,best-practices"],
  { encoding: "utf8", maxBuffer: 64 * 1024 * 1024, shell: true },
);
if (result.status !== 0) {
  console.error(result.stderr);
  process.exit(result.status ?? 1);
}
const report = JSON.parse(result.stdout);
const scores = Object.fromEntries(Object.entries(report.categories).map(([k, v]) => [k, Math.round(v.score * 100)]));
console.log(JSON.stringify({ url, scores }, null, 2));
process.exit(Object.values(scores).some((s) => s < 90) ? 2 : 0);
