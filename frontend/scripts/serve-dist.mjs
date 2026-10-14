// Serves dist/ the way a production host would: brotli or gzip, long-lived caching for hashed assets,
// SPA fallback, and /api proxied to the backend. Used for Lighthouse runs.
// Usage: node scripts/serve-dist.mjs [port] [backend-url]
import { createServer, request } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { brotliCompressSync, gzipSync, constants } from "node:zlib";
import { fileURLToPath } from "node:url";

const root = join(fileURLToPath(new URL(".", import.meta.url)), "..", "dist");
const port = Number(process.argv[2] ?? 4173);
const backend = new URL(process.argv[3] ?? "http://localhost:8765");
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff", ".txt": "text/plain", ".xml": "application/xml", ".json": "application/json" };
const COMPRESSIBLE = new Set([".html", ".js", ".css", ".svg", ".txt", ".xml", ".json"]);
const cache = new Map();

async function load(file) {
  if (cache.has(file)) return cache.get(file);
  const body = await readFile(file);
  const ext = extname(file);
  const entry = { body, type: TYPES[ext] ?? "application/octet-stream", ext };
  if (COMPRESSIBLE.has(ext)) {
    entry.br = brotliCompressSync(body, { params: { [constants.BROTLI_PARAM_QUALITY]: 9 } });
    entry.gz = gzipSync(body, { level: 9 });
  }
  cache.set(file, entry);
  return entry;
}

createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://x");
  if (url.pathname.startsWith("/api/")) {
    const upstream = request({ host: backend.hostname, port: backend.port, path: req.url, method: req.method, headers: req.headers }, (r) => {
      res.writeHead(r.statusCode ?? 502, r.headers);
      r.pipe(res);
    });
    upstream.on("error", () => { res.writeHead(502).end(); });
    req.pipe(upstream);
    return;
  }
  let file = join(root, normalize(url.pathname).split("/").filter(Boolean).join("/"));
  if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
  try { if ((await stat(file)).isDirectory()) file = join(file, "index.html"); } catch { file = join(root, "index.html"); }
  try {
    const entry = await load(file).catch(() => load(join(root, "index.html")));
    const accept = String(req.headers["accept-encoding"] ?? "");
    const headers = { "Content-Type": entry.type, "Cache-Control": url.pathname.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-cache", Vary: "Accept-Encoding" };
    let body = entry.body;
    if (entry.br && accept.includes("br")) { body = entry.br; headers["Content-Encoding"] = "br"; }
    else if (entry.gz && accept.includes("gzip")) { body = entry.gz; headers["Content-Encoding"] = "gzip"; }
    headers["Content-Length"] = body.length;
    res.writeHead(200, headers).end(body);
  } catch { res.writeHead(500).end(); }
}).listen(port, () => console.log(`serving dist on http://localhost:${port}`));
