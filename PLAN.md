# Patent Prior-Art Search and Novelty Report Platform: Build Plan

Product name for UI and docs: **PriorArt Atlas** (working name, replaceable via one config constant).

Purpose: take an invention disclosure, semantically search real US patents, build a claim-by-claim comparison against the closest prior art, and produce a novelty and obviousness risk summary for attorney review.

Workflow mirrored: disclosure intake, search, claim charting, risk flagging, attorney review, report export.

Global rules for the developer:
1. Use only free and open-source tools and free API tiers listed here.
2. Keep wording professional everywhere (code, UI, commits, docs). Do not mention any AI vendor assistant names in the product, README or comments, except the two configured LLM providers in the technical stack section.
3. Never use the long dash character in any file. Use a hyphen, comma or colon.
4. A complete, professional `README.md` is a release requirement (see Phase 11).
5. Every phase ends with its acceptance criteria met and merged before starting the next.

---

## 1. Technology Stack (all free)

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| API | FastAPI, Pydantic v2, Uvicorn, SQLAlchemy 2.0, Alembic, psycopg 3 |
| Database | PostgreSQL 16 with pgvector 0.8 (HNSW index) and built-in full-text search (tsvector) |
| Embeddings | Hugging Face `BAAI/bge-small-en-v1.5` (384 dim, MIT) via `sentence-transformers`, CPU. Optional upgrade: `BAAI/bge-base-en-v1.5` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` (Apache 2.0), local, CPU |
| LLM provider A | Groq API, model `openai/gpt-oss-20b`, OpenAI-compatible endpoint `https://api.groq.com/openai/v1` |
| LLM provider B | Google Gemini API via `google-genai` SDK. Model id read from env `GEMINI_MODEL` (default `gemini-3.1-flash-lite`). Do not use Gemini 2.5 family, it is scheduled for shutdown on 16 Oct 2026. Verify free eligibility at aistudio.google.com/rate-limit |
| Background jobs | PostgreSQL job table with `FOR UPDATE SKIP LOCKED` and a worker process (no Redis) |
| Frontend | React 18, Vite, TypeScript, Tailwind CSS, shadcn/ui (Radix), TanStack Query and Table, React Router, react-hook-form with zod, Framer Motion, lucide-react icons, Apache ECharts via `echarts-for-react` |
| PDF export | Jinja2 plus WeasyPrint |
| Auth | argon2-cffi, PyJWT, httpOnly refresh cookie, RBAC |
| Security tooling | bandit, pip-audit, npm audit, Trivy, pre-commit, ruff, mypy |
| Testing | pytest, httpx, Playwright (e2e), Vitest, Testing Library |
| Packaging | Docker Compose, Caddy (automatic TLS in production) |
| CI | GitHub Actions |
| Fonts and icons | Inter and IBM Plex Mono via `@fontsource` (OFL), lucide-react (ISC) |
| Images | Unsplash and Pexels (free licenses), unDraw illustrations. Keep an `ATTRIBUTIONS.md` |

Free LLM limits to design around (verified Oct 2026, always re-check the account limits page):
- Groq `openai/gpt-oss-20b` free plan: 30 requests per minute, 1,000 requests per day, **8,000 tokens per minute**, 200,000 tokens per day. The 8K per minute cap is the binding limit, so every call must stay below about 3,500 total tokens (input plus output including reasoning).
- Gemini free tier: limits are per model and per project and are shown only in AI Studio. Configure conservative defaults (10 requests per minute, 250 per day) in env and let the router learn from 429 responses.
- Gemini free tier terms allow Google to use submitted content to improve products. Therefore the app must warn users, default to synthetic or public demo disclosures, and support a "local only" mode with no LLM calls (deterministic template report).

---

## 2. Architecture Summary

```
React SPA  <->  FastAPI  <->  PostgreSQL + pgvector
                  |              (patents, chunks, cases, charts, billing, analytics)
                  +-- Worker (pipeline jobs, SKIP LOCKED)
                  +-- Local models (embeddings, reranker)
                  +-- LLM Gateway -> Groq (primary) / Gemini (fallback) with cache + token budget
```

Repository layout:
```
/backend        app/, alembic/, tests/
/frontend       src/, public/, e2e/
/dataset        raw/ processed/ demo/ seed/ disclosures/ README.md
/scripts        download_*, build_corpus.py, embed_corpus.py, seed_business_data.py, evaluate_search.py
/docs           architecture.md, api.md, security.md, runbook.md, screenshots/
/docker         compose files, Dockerfiles, Caddyfile
README.md  ATTRIBUTIONS.md  LICENSE  .env.example
```

---

## 3. Token-Minimization Design (core requirement)

Target: **under 9,000 total LLM tokens per end-to-end case** (3 charted references, about 8 disclosure elements).

Principle: do everything possible locally and deterministically; the LLM only does language understanding on tiny, pre-filtered inputs.

| Step | Method | LLM tokens |
|---|---|---|
| Disclosure parsing into elements | One call, strict JSON schema, input capped at 1,500 words, output cap 500 tokens | about 1,200 to 1,800 |
| Query building | Local: embed the title, each element and the full summary | 0 |
| Retrieval | Local hybrid search (vector plus full text, reciprocal rank fusion) | 0 |
| Reranking | Local cross-encoder over top 40 | 0 |
| Passage selection per element | Local: embed each reference's claims, abstract and summary sentences; take top 2 passages per element (max 120 words each) | 0 |
| Pre-classification | Local: cosine below 0.35 marks "not found" and above 0.88 plus keyword overlap marks "likely disclosed", both still shown as machine-labelled. Only the ambiguous middle band goes to the LLM | 0 |
| Claim charting | One call per reference, batching only ambiguous elements with their 2 passages. Output: compact JSON `{e, s, p, r}` with rationale at most 25 words | about 700 to 1,100 per reference |
| Risk logic (anticipation vs obviousness) | Deterministic rules over the chart (see Phase 5) | 0 |
| Executive summary | One call, input is compact JSON of statuses and ids only (no passage text), output cap 350 words | about 900 |

Mandatory mechanics:
1. Stable system prompts placed first so Groq prompt caching applies (cached tokens do not count toward rate limits).
2. Response cache table keyed by SHA-256 of (task, normalized input, schema version). Identical disclosures cost nothing on rerun.
3. `max_completion_tokens` set on every call. For `gpt-oss-20b` set `reasoning_effort` to `low`.
4. Strict JSON schema output with Pydantic validation. At most one repair retry, and the repair prompt contains only the invalid field, not the full context.
5. Token accounting on every call (`llm_calls` table) feeding the analytics dashboard.
6. Router rules: use Groq first. On 429, 5xx, timeout or when the local token bucket predicts an 8K per minute overflow, switch to Gemini. Circuit breaker opens for 60 seconds after 3 failures. If both are unavailable, produce a deterministic template report and mark it "machine summary, no LLM".
7. Regenerate only what changed. Editing one element reruns only that element's chart cell.

---

## 4. Dataset Section

### 4.1 Sources and licenses (check again before any redistribution)

| Source | What it gives | Where | License |
|---|---|---|---|
| PatentsView bulk tables (granted patents 1976 onward, published applications 2001 onward) | Title, abstract, claims, CPC, assignee, citations, summary text | `https://patentsview.org/download/data-download-tables` (also listed in the USPTO Open Data Portal bulk directory at `https://data.uspto.gov/bulkdata`) | CC BY 4.0, attribution to PatentsView required |
| HUPD, Harvard USPTO Patent Dataset (applications 2004 to 2018, full text: abstract, claims, background, summary, description) | Full text for passage-level comparison | `https://huggingface.co/datasets/HUPD/hupd` | Hugging Face metadata says CC BY-SA 4.0 while the dataset card text says CC BY 4.0. Treat as the stricter CC BY-SA 4.0. Any redistributed derived data must keep attribution and share-alike. Record the decision in `dataset/README.md` |
| Synthetic business and usage history | Revenue and analytics history | Generated by `scripts/seed_business_data.py` | Project-owned |
| Sample invention disclosures | Demo inputs | Authored by developer in `dataset/disclosures/` | Project-owned |

Notes:
- The legacy PatentsView search API is not required. Use bulk files only (offline, reproducible).
- HUPD hosts per-year archives at `data/YYYY.tar.gz` (full set about 238 GB). Do not download everything. Use `data/sample-jan-2016.tar.gz` for development and one or two full years (for example 2013 and 2014) for the demo. Metadata file: `hupd_metadata_2022-02-22.feather`.
- Prior-art validity: published applications and granted patents are both legitimate prior art references, so keep a `source` column (`PV_GRANT`, `HUPD_APP`) and show it in the UI.

### 4.2 Folder structure

```
dataset/
  README.md              sources, licenses, exact file names, download dates, SHA-256 checksums, row counts
  raw/                   gitignored. PatentsView TSV zips, HUPD tarballs
  processed/             gitignored. corpus.parquet, chunks.parquet, embeddings.parquet
  demo/                  committed. 500 patent sample (JSONL) for tests and quick start
  seed/                  committed. plans.csv, clients.csv, subscriptions.csv, invoices.csv, usage_events.csv, review_events.csv
  disclosures/           committed. 8 sample disclosures as JSON plus a markdown copy each
```

### 4.3 Files to download

PatentsView (granted), for years 2015 to 2024 (adjust to disk size):
- `g_patent.tsv` (patent_id, title, date, type, number of claims)
- `g_patent_abstract.tsv`
- `g_claims_{year}.tsv` (patent_id, claim sequence, claim number, claim text, dependent flag)
- `g_cpc_current.tsv`
- `g_assignee_disambiguated.tsv`
- `g_brf_sum_text_{year}.tsv` (brief summary text, smaller than full description)
- `g_us_patent_citation.tsv` (used only for evaluation ground truth)
- Data dictionary from the same page. Confirm exact column names against it before writing loaders.

Detailed description text files are very large. Do not load them. Use the summary text plus claims plus abstract for granted patents, and use HUPD for full-description coverage.

### 4.4 How to use it

1. `scripts/download_patentsview.py` and `scripts/download_hupd.py` (uses `huggingface_hub.hf_hub_download` for chosen years only). Both are resumable, verify checksums and log to `dataset/README.md`.
2. `scripts/build_corpus.py`:
   - Join tables on `patent_id`, filter to **demo technology areas** by CPC subclass: G06N, G06F, G06Q, G16H, H04L, H04W, H01M, B60L, A61B, C12N. This keeps relevant, dense prior art for demos.
   - Cap the demo corpus at about 60,000 patents (PatentsView) plus about 20,000 applications (HUPD). Configurable.
   - Clean text (strip claim numbering artifacts, normalize whitespace), parse each claim into independent or dependent, and store parent claim number.
   - Write `corpus.parquet`.
3. Chunking (in `build_corpus.py`):
   - One chunk per claim (claims are the key unit for claim charts).
   - One chunk for the abstract.
   - Summary and description text split into passages of 80 to 150 words with sentence boundaries.
   - Each chunk has `patent_id`, `chunk_type` (`claim`, `abstract`, `summary`, `description`), `claim_number`, `text`, `char_start`, `char_end`.
4. `scripts/embed_corpus.py`: batch embed with `bge-small-en-v1.5` (normalize embeddings, batch size 64, resumable by chunk id). Expect tens of minutes on CPU for the demo corpus.
5. `scripts/load_to_postgres.py`: bulk `COPY` into tables, then create HNSW and GIN indexes after load.
6. `scripts/seed_business_data.py`: generates 24 months of history (fixed random seed) for clients, subscriptions, invoices, usage and reviews. Label it as demo data in the UI footer of the dashboard and in the README.
7. `scripts/evaluate_search.py`: uses examiner-cited references from `g_us_patent_citation` as ground truth (see Phase 10).
8. Quick start path: loading `dataset/demo/` alone must give a working app in under 5 minutes.

Disclosure samples (author 8, each with title, field, problem, solution, 6 to 10 enumerated elements, optional dependent features, priority date): federated learning for hospital imaging, battery thermal runaway early detection, cold-chain logistics routing, wearable arrhythmia detection, retrieval-based clinical note coding, vehicle-to-grid charging scheduler, zero-trust device attestation, enzyme-based plastic degradation process.

---

## 5. Phase-wise Development Plan

### Phase 0: Foundation (1 to 2 days)

Tasks:
- Create monorepo layout from section 2, git hooks (ruff, mypy, bandit, prettier, eslint), `.editorconfig`, conventional commits.
- Docker Compose services: `db` (image `pgvector/pgvector:pg16`), `api`, `worker`, `web`. Healthchecks on all.
- Settings via Pydantic Settings and `.env.example` (no secrets committed). Keys: `DATABASE_URL`, `JWT_SECRET`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `LLM_MODE` (`auto`, `groq`, `gemini`, `local_only`), `FERNET_KEY`, `CORS_ORIGINS`.
- Structured JSON logging (structlog) with request ids.
- GitHub Actions: lint, type check, tests, `pip-audit`, `npm audit`, Trivy image scan.

Acceptance: `docker compose up` starts all services healthy; CI green on an empty test.

### Phase 1: Dataset acquisition and corpus build (2 to 3 days)

Tasks: implement scripts and folder layout from section 4. Write `dataset/README.md` with a table of every file, URL, license, download date, checksum, row count. Build `dataset/demo/` sample.

Acceptance: `corpus.parquet` and `chunks.parquet` produced; row counts logged; random 20 patents manually spot-checked for correct claim parsing; no duplicates by `patent_id`.

### Phase 2: Database schema and semantic search (3 days)

Schema (Alembic migrations):
- Reference data: `patents` (id, source, title, abstract, filing_date, grant_date, assignee, cpc_codes[], url), `patent_claims` (patent_id, number, text, is_independent, parent), `patent_chunks` (id, patent_id, type, claim_number, text, `embedding vector(384)`, `tsv tsvector`).
- Case data: `cases`, `disclosures`, `disclosure_elements`, `search_runs`, `search_results`, `claim_charts`, `chart_cells`, `reports`, `report_versions`, `review_events`.
- Platform data: `users`, `roles`, `audit_log`, `jobs`, `llm_calls`, `llm_cache`.
- Business data: `clients`, `plans`, `subscriptions`, `invoices`, `invoice_lines`, `usage_events`.
- Indexes: HNSW on `embedding` with `vector_cosine_ops` (m 16, ef_construction 128, `hnsw.ef_search` 80), GIN on `tsv`, B-tree on dates and CPC (GIN on `cpc_codes`).

Search service (`app/search/`):
1. Embed query set locally: whole-disclosure summary, title, each element.
2. Vector search over `claim` and `abstract` chunks, top 100 per query. Full-text search with `websearch_to_tsquery`, top 100.
3. Fuse with reciprocal rank fusion (k 60). Aggregate by patent (max score plus mean of top 3).
4. Filters: publication date earlier than the disclosure priority date, optional CPC prefix, source.
5. Rerank top 40 with the cross-encoder. Return top 10 with matched chunk ids and scores.
6. Suggest CPC areas by voting over the top 30 results (no LLM).

Acceptance: sample disclosure returns relevant results in under 2 seconds p95 on the demo corpus; EXPLAIN shows HNSW index use.

### Phase 3: Backend core, authentication, authorization, security (3 days)

Authentication:
- Registration is admin-invited only. Passwords hashed with Argon2id. Minimum length 12, breached-password check against a small local common-password list.
- Login returns a 15 minute JWT access token (in memory on the client) and a 7 day rotating refresh token in an `httpOnly`, `Secure`, `SameSite=Strict` cookie. Refresh token hashes stored server-side, reuse detection revokes the family.
- Account lockout with backoff after 5 failures. Optional TOTP second factor (`pyotp`).

Authorization (RBAC plus ownership):
- Roles: `admin` (users, billing, analytics, all cases), `attorney` (own and shared cases, approve reports), `analyst` (create cases, run searches, cannot approve), `viewer` (read-only on shared cases).
- Enforce through FastAPI dependencies and a policy module with one function per permission. Case-level sharing table. Return 404 (not 403) for objects the user cannot see.
- Analytics and revenue endpoints: `admin` only (with a read-only `finance` flag optional).

Data security:
- Transport: TLS via Caddy in production. HSTS, CSP, X-Content-Type-Options, Referrer-Policy, Permissions-Policy headers.
- Application-level encryption of disclosure text with Fernet (`cryptography`), key from env, key rotation supported via `MultiFernet`.
- Strict Pydantic validation, upload size and type limits, parameterized queries only, output escaping, CORS allow-list, rate limiting (`slowapi`) with stricter limits on auth and LLM endpoints.
- Audit log for login, case view, export, approval, role change, with user, IP, timestamp.
- Prompt-injection hygiene: reference patent text and disclosures are passed as quoted data blocks, the system prompt states they are untrusted, outputs are schema-validated, no tool use.
- Secrets never logged. Redact disclosure text in logs.
- Data retention setting per case and a hard-delete endpoint.

API surface (versioned under `/api/v1`): `auth/*`, `users/*`, `cases` CRUD, `cases/{id}/disclosure`, `cases/{id}/run` (queues job), `cases/{id}/progress` (Server-Sent Events), `cases/{id}/results`, `cases/{id}/chart`, `chart/cells/{id}` (override), `cases/{id}/report` (generate, version, export PDF), `cases/{id}/review` (submit, approve, request changes), `analytics/*`, `billing/*`, `health`. OpenAPI docs enabled in non-production only.

Acceptance: auth and RBAC test matrix passes (every role against every endpoint); OWASP ZAP baseline scan (free) shows no high findings; secrets scan clean.

### Phase 4: LLM gateway with free-tier switching (2 to 3 days)

`app/llm/gateway.py`:
- Provider interface `complete(task, messages, schema, max_tokens) -> LLMResult(text, json, tokens_in, tokens_out, provider, latency_ms)`.
- `GroqProvider` (OpenAI-compatible client, model `openai/gpt-oss-20b`, `reasoning_effort=low`) and `GeminiProvider` (`google-genai`, JSON response schema, thinking budget minimized).
- Router per section 3: primary Groq, fallback Gemini, circuit breaker, exponential backoff with jitter (`tenacity`), honoring `retry-after` headers.
- Local token bucket per provider using response headers (`x-ratelimit-remaining-tokens`) plus a tokenizer-free estimate (characters divided by 4) before sending. If a request would exceed the per-minute budget, wait or switch provider.
- Daily quota tracker (200K tokens Groq, configurable Gemini) stored in Postgres, surfaced in the admin dashboard.
- Manual override: per-case and global setting `LLM_MODE`, plus a model selector in the admin settings page.
- Prompt library in `app/llm/prompts/` with versioned files and golden tests. Prompts must be short, instruction first, schema last.
- Every call writes to `llm_calls` and `llm_cache`.

Acceptance: simulated 429 and timeouts fall over correctly; unit tests with mocked providers; token counts recorded; one real smoke test per provider in a manual CI job.

### Phase 5: End-to-end analysis pipeline (4 to 5 days)

Job stages (worker, progress emitted via SSE, each stage idempotent and resumable):

1. **Intake**: validate disclosure. Fields: title, technical field, problem, solution description, key elements (user-entered or extracted), priority date, jurisdiction (default US), confidentiality flag. If elements are not given, one LLM call extracts 6 to 10 atomic elements with ids `E1..En` using the strict schema. User can edit them before the run continues (checkpoint).
2. **Search**: Phase 2 service. Persist top 10 with scores.
3. **Reference selection**: take top 3 (configurable 1 to 5) after rerank. Load each reference's independent claims, abstract and summary chunks.
4. **Passage selection**: per element and per reference, local top 2 passages by cosine, each at most 120 words, with offsets for highlighting.
5. **Claim charting**: pre-classify locally, send ambiguous elements per reference in one batched call. Cell fields: `status` (`disclosed`, `partial`, `not_found`), `confidence` 0 to 1, `passage_id`, `excerpt` (verbatim substring, validated server-side to exist in the source text), `rationale` (at most 25 words), `method` (`local` or `llm`). Reject and downgrade any LLM excerpt that is not a verbatim substring.
6. **Risk logic (deterministic)**:
   - Anticipation risk (35 U.S.C. 102 style): any single reference with all elements `disclosed`: **High**.
   - Obviousness risk (35 U.S.C. 103 style): union of two or three references covers all elements, or one reference covers at least 80 percent with the rest `partial`: **Medium-High** if combination is within the same CPC subclass, else **Medium**.
   - Otherwise **Low**, listing the uncovered elements as potential points of novelty.
   - Output a numeric score 0 to 100 and a per-element novelty table (which reference covers which element).
7. **Report generation**: one summary call with compact JSON input. Sections: executive summary, closest references, element coverage matrix, novelty and obviousness risk, suggested claim-drafting considerations (as questions for the attorney), limitations. Always append the fixed legal disclaimer (decision support, not legal advice, search limited to the indexed corpus).
8. **Attorney review**: states `draft`, `in_review`, `changes_requested`, `approved`. Attorney can override any cell (stores original, override, reason, user, time), add notes, and approve. Approval freezes a versioned snapshot, writes an audit event and records an approval stamp (name, role, timestamp, version hash).
9. **Export**: PDF (WeasyPrint) with cover page, chart tables and highlighted excerpts; also JSON export.

Acceptance: each of the 8 sample disclosures runs end to end; total LLM tokens per run at most 9,000 (median) and logged; every excerpt in output is a verbatim substring of its source; rerun of an identical case uses zero LLM tokens.

### Phase 6: Billing ledger, usage metering and analytics data layer (3 days)

No real payment processor. Build an internal, realistic ledger (free and fully self-contained).

- Plans: Starter, Professional, Enterprise with monthly price, included reports, overage price per report, seats.
- Every completed case creates a `usage_event` (type `report_generated`, units, plan, client). A monthly job generates invoices with lines for subscription, overage and add-ons, with statuses `draft`, `issued`, `paid`, `overdue`, `void`.
- Revenue metrics computed in SQL views or materialized views (refreshed nightly and on demand): MRR, ARR, new, expansion, contraction and churned MRR, net revenue retention, gross margin proxy (revenue minus modelled infrastructure and token cost), ARPA, invoice aging, collections rate, revenue by plan, client, industry and region.
- Operational metrics: cases per day, reports per attorney, turnaround time (intake to approval), review backlog, risk distribution, top CPC areas searched, search latency percentiles, LLM tokens by provider, fallback rate, cache hit rate, tokens per case, estimated cost per case.
- `scripts/seed_business_data.py`: 24 months history, 40 to 60 clients across law firms, corporate IP teams and universities; seasonality, growth trend, a few churn events and upgrades; realistic invoice payment delays. Deterministic with a fixed seed. New live usage appends to the same tables so the dashboard mixes seeded history with real activity.

Analytics API (admin only): `GET /analytics/revenue/summary`, `/revenue/timeseries?metric=&granularity=day|week|month&from=&to=&compare=previous`, `/revenue/breakdown?by=plan|client|industry`, `/ops/*`, `/llm/*`, plus `?format=csv` export on all.

Acceptance: metrics reconcile (sum of invoice lines equals revenue totals, MRR walk adds up); SQL tests with fixed seed fixtures; queries under 300 ms.

### Phase 7: Frontend foundation and public website (5 to 6 days)

Design system:
- Tailwind theme tokens: primary deep navy (`#0B1F3A`), accent teal (`#0E7C86`), warm neutral grays, status colors (risk high red, medium amber, low green), 8 px spacing grid, 12 column layout, max content width 1200 px.
- Typography: Inter for UI and headings, IBM Plex Mono for patent numbers and excerpts. Type scale 14, 16, 18, 24, 32, 48, 60.
- Components via shadcn/ui: Button, Card, Tabs, Dialog, Sheet, Tooltip, Table, Badge, Accordion, Navigation Menu, Toast, Skeleton, Command palette.
- Accessibility WCAG 2.1 AA: focus rings, keyboard navigation, color contrast, reduced motion, semantic landmarks. Responsive from 360 px to 1920 px. Light theme for the website; light and dark for the app.
- Motion: subtle Framer Motion fade and rise on scroll, no heavy effects.
- SEO and performance: meta tags, Open Graph, sitemap, lazy-loaded images in AVIF or WebP with width and height set, Lighthouse score targets 90 or above.

Public site pages and content (write real, professional copy, no filler text):

**Global header**: slim utility bar (Contact sales, Support, language selector placeholder), sticky main nav with mega menu: Platform, Solutions, Resources, Company, Pricing, plus a prominent **Log in** button (outlined) and **Request a demo** button (filled). Log in goes to `/login`.

**Home page sections, in order**
1. Hero: headline "Prior-art intelligence for confident patent decisions", subhead "Search millions of US patent records semantically, chart every claim element against the closest references, and deliver attorney-ready novelty reports in minutes." Primary CTA "Request a demo", secondary "Log in". Right side: product screenshot of the claim chart viewer on a soft gradient with floating risk badge cards.
2. Trust band: "Trusted by IP teams worldwide" with six fictional firm wordmarks created as simple text logos (do not use real company logos or trademarks). Mark testimonials and logos as sample content in the demo footnote.
3. Key figures band: for example "8M+ patent documents indexed" (use the real count of the loaded corpus in the demo, never inflate), "under 5 min from disclosure to report", "100% excerpt traceability", "Attorney review built in".
4. How it works (5 steps with icons matching the workflow): Disclosure intake, Semantic search, Claim charting, Risk assessment, Attorney review.
5. Platform capabilities (3 by 2 grid): Semantic and keyword hybrid search, Claim chart viewer, Novelty and obviousness risk scoring, Verbatim excerpt evidence, Collaboration and review workflow, Analytics and reporting.
6. Product tour: tabbed large screenshots (Search results, Claim chart, Risk report, Analytics dashboard) captured from the real app.
7. Solutions by role: Patent attorneys, Corporate IP counsel, R and D and innovation teams, Universities and tech transfer offices. Each with 3 outcome bullets.
8. Security and governance: encryption in transit and at rest, role-based access, audit trails, data retention controls. State only controls that are actually implemented. Do not claim certifications that are not held.
9. Customer stories: three cards with outcome metrics, clearly labelled "Sample story" in the demo build.
10. Insights and resources: three article cards (guide to prior-art searching, understanding claim charts, novelty versus obviousness explained). Write 3 short articles (400 to 600 words) for `/resources`.
11. Pricing preview: three plans (Starter, Professional, Enterprise) matching the seeded plans table.
12. FAQ accordion (8 questions: data sources, accuracy, confidentiality, jurisdictions, LLM use, export formats, review workflow, limitations).
13. Final CTA banner and footer.

**Footer**: five columns (Platform, Solutions, Resources, Company, Legal), social icons, newsletter field (non-functional or stored locally), copyright line, links to Privacy Policy, Terms of Use, Cookie Notice, Accessibility Statement, Security. Include a short data attribution line crediting PatentsView and HUPD with their licenses.

**Other pages**: Platform (feature deep dives with alternating image and text), Solutions (one page with anchored role sections), Pricing (plan comparison table plus add-ons plus FAQ), Security, About (mission, values, leadership placeholders as fictional sample profiles), Contact (validated form stored in DB), Resources (list and article detail), 404 page, legal pages with real placeholder policy text reviewed by the developer.

**Images and media**
- Photography from Unsplash or Pexels (free license): modern office and legal setting, engineers in a lab, team collaborating, abstract network and data visuals, university campus. Store optimized copies in `frontend/public/images/` and list photographer and URL in `ATTRIBUTIONS.md`.
- Illustrations: unDraw for empty states and feature icons, recolored to the brand palette.
- Product visuals: real screenshots from the running app (1600 by 1000, taken from seeded demo data), with device frame mockups made in CSS.
- Hero background: subtle CSS or SVG gradient mesh, no stock video.
- Avoid images with identifiable brand logos or recognizable people tied to claims.

Acceptance: Lighthouse performance, accessibility and SEO at 90 or above on Home; all pages responsive; no placeholder lorem ipsum; every Log in link routes correctly.

### Phase 8: Application frontend (6 to 7 days)

Authenticated app shell: left sidebar (Dashboard, Cases, New case, Analytics (admin), Admin (admin)), top bar with global search, notifications, user menu, theme toggle. Breadcrumbs on all pages.

Screens:
1. **Login**: split layout (brand panel with image and a short security note, form panel), email and password, optional TOTP step, error states, "Forgot password" (admin reset flow). Demo credentials shown only in the README, not on the page.
2. **Cases dashboard**: KPI cards (open cases, awaiting review, approved this month, average turnaround), table with filters (status, risk, owner, date), sort, pagination, risk badges, status chips, row actions.
3. **New case wizard** (stepper, autosave drafts): Step 1 Disclosure (title, field, problem, solution, file paste or upload of `.txt` and `.md`), Step 2 Elements (editable list with add, split, merge, reorder, AI-extracted or manual), Step 3 Search settings (priority date, CPC filter with suggestions, sources, number of references to chart), Step 4 Review and run. Show a confidentiality notice and the active LLM mode.
4. **Run progress**: live stage tracker via SSE, elapsed time, tokens used so far.
5. **Case workspace** with tabs: Overview, Disclosure, Search Results, Claim Chart, Risk Report, Activity.
   - Search Results: ranked list with score bars, assignee, dates, CPC chips, matched passage preview, source badge, "Add to chart" and "Exclude".
   - **Claim Chart Viewer (the signature screen)**: two panes side by side. Left pane: disclosure elements E1..En in a sticky list with coverage status per selected reference. Right pane: reference selector tabs (top 3 plus added), reference header (number, title, assignee, dates, link), and for the selected element the matched passages with verbatim highlighted excerpts, confidence meter, method tag (local or LLM) and rationale. Row-aligned grid on wide screens, stacked on narrow. Status chips (Disclosed, Partial, Not found), color plus icon plus text (not color alone). Click an element to scroll and highlight the matching passage in the full reference text drawer. Keyboard shortcuts (J and K to move between elements, 1 2 3 to set status). Attorney override dialog with reason. Legend and filter ("show only uncovered elements"). Print stylesheet.
   - Risk Report: risk gauge, coverage heatmap (elements by references), summary text, limitations, edit mode for the attorney, version history with diff.
   - Activity: audit timeline.
6. **Review flow**: submit for review, assign attorney, comments per cell, approve with confirmation modal, export PDF.
7. **Admin**: users and roles, LLM settings (mode, model ids, quota meters for Groq and Gemini), data corpus status (counts, last load), audit log viewer.
8. Empty, loading (skeletons), error and offline states on every screen. Toasts for all mutations.

Frontend security: access token in memory only, silent refresh, route guards by role, no secrets in bundle, sanitize any rendered HTML (use DOMPurify only if rendering rich text), CSP-compatible build.

Acceptance: Playwright e2e of the full journey (login, create case, run, view chart, override, approve, export) on the demo dataset; Vitest coverage for chart status logic; axe accessibility checks pass on key screens.

### Phase 9: Revenue and analytics dashboard (4 days)

Route `/app/analytics` (admin only), three tabs, shared filter bar (date range presets: 30 days, 90 days, 12 months, 24 months, custom; granularity day, week, month; compare to previous period toggle; client and plan filters). Export CSV and PNG per chart. All data from the Phase 6 API, never hard-coded in the UI.

**Tab 1: Revenue**
- KPI row with sparklines and period delta: MRR, ARR, Net revenue retention, ARPA, Collections rate, Outstanding receivables.
- Combo chart: monthly revenue (bars, stacked by subscription and overage) with trend line and previous-period overlay.
- MRR movement waterfall: new, expansion, contraction, churn.
- Revenue by plan (donut) and by client industry (horizontal bars), top 10 clients table with revenue, usage, trend.
- Invoice aging stacked bars (current, 1 to 30, 31 to 60, 60 plus) and invoice status table.
- Cohort retention heatmap (signup month by months since signup).
- Monthly growth rate line with 3 month moving average.

**Tab 2: Usage and operations**
- Reports generated per month (area), cases by status funnel (intake, searched, charted, reviewed, approved).
- Risk distribution (stacked bars by month), technology areas heatmap (CPC subclass by month).
- Turnaround time distribution (box or histogram) and p50 and p90 trend.
- Review backlog and attorney throughput table.
- Search latency p50 and p95 line.

**Tab 3: LLM and cost efficiency**
- Tokens by provider by day (stacked area, Groq vs Gemini), fallback rate, cache hit rate, tokens per case trend with the 9,000 target line, quota usage gauges for today.
- Estimated cost per case (modelled at paid list prices for reference) vs revenue per case, giving a gross margin trend.

Chart standards (ECharts): consistent palette tied to brand tokens, gridlines light, tooltips with exact values and units, axis labels with units, legends toggleable, number formatting with thousands separators and currency, responsive resize, dark mode theme, accessible titles and descriptions, empty-state messages. Show a discreet "Includes demo data through <date>" note.

Acceptance: values on the dashboard reconcile with the database via SQL checks; every chart responds to filters; load time under 2 seconds with 24 months of seeded data.

### Phase 10: Testing, evaluation, hardening (3 to 4 days)

- Unit and integration tests, backend coverage at least 80 percent on services and policies.
- **Search evaluation**: `scripts/evaluate_search.py` takes 200 granted patents in the corpus, uses claim 1 text as a pseudo disclosure, and checks whether examiner-cited references present in the corpus appear in the top 10, top 50 and top 100. Report recall at K and MRR. Targets: recall at 50 of at least 0.55 on demo corpus (tune chunking, model choice, RRF weights, reranker depth). Save results to `docs/evaluation.md`.
- **Chart quality check**: manually label 30 element-reference pairs, measure agreement of the pre-classifier and LLM cells, tune thresholds (0.35 and 0.88 in section 3).
- **Token budget test**: assert median tokens per case below 9,000 and p95 below 12,000 across the 8 sample disclosures.
- Load test with Locust (free): 20 concurrent users on search and analytics endpoints.
- Security: ZAP baseline, dependency audits, authorization fuzz tests, JWT tamper tests, rate limit tests, secrets scan (gitleaks).
- Accessibility: axe in e2e, manual keyboard pass.
- Backups: `pg_dump` script and restore test.

Acceptance: all targets met or documented with rationale; zero high or critical vulnerabilities open.

### Phase 11: Packaging, documentation, demo (2 to 3 days)

**README.md (mandatory, professional, complete)**. Required sections: overview and screenshots, feature list, architecture diagram, tech stack, quick start (demo dataset in under 5 minutes), full setup (dataset download and build commands), environment variable reference, LLM provider setup and free-tier limits with the switching behavior and `LLM_MODE`, token-efficiency design summary, security model (authentication, roles, encryption, audit), dataset sources, licenses and attribution, API overview with link to OpenAPI, testing commands, project structure, demo accounts and a guided demo script, known limitations and legal disclaimer, deployment notes, contributing and license. Also deliver `docs/architecture.md`, `docs/security.md`, `docs/runbook.md`, `ATTRIBUTIONS.md`.

Demo preparation:
- Seed accounts: `admin`, `attorney`, `analyst`, `viewer` with documented demo passwords (changed on first deployment).
- Load full demo corpus, 8 sample disclosures with 3 pre-completed approved cases so dashboards and lists look populated.
- Record a short walkthrough script (no video required): login, new case, run, chart viewer, override, approve, export, analytics.
- Production compose file with Caddy TLS, non-root containers, read-only filesystem where possible, resource limits.

Acceptance: a new developer follows the README on a clean machine and reaches the running demo without help; all docs reviewed for professional wording and for absence of the long dash character.

---

## 6. Definition of Done (project level)

- Full flow works: disclosure, search, claim chart, risk report, attorney approval, PDF export.
- Median tokens per case at most 9,000, automatic Groq to Gemini switching verified, local-only mode works.
- Every chart excerpt is a verified verbatim substring of its source text.
- Authentication, RBAC, encryption, audit logging and rate limiting in place and tested.
- Website and app look consistent, responsive and accessible; Log in button present on every public page.
- Revenue and analytics dashboard shows 24 months of reconciled history plus live data.
- Dataset folder, licenses and attributions documented; README complete.
