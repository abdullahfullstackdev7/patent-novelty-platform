// Shapes returned by the backend API (see backend/app/api/v1/schemas.py).

export type Role = "admin" | "attorney" | "analyst" | "viewer";
export type CellStatus = "disclosed" | "partial" | "not_found";
export type LlmMode = "auto" | "groq" | "gemini" | "local_only";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  client_id: string | null;
  is_active: boolean;
  totp_enabled: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface CasePermissions {
  edit: boolean;
  delete: boolean;
  share: boolean;
  review: boolean;
}

export interface CaseItem {
  id: string;
  title: string;
  status: string;
  stage: string | null;
  risk_level: string | null;
  risk_score: number | null;
  priority_date: string | null;
  jurisdiction: string;
  llm_mode: LlmMode;
  confidential: boolean;
  retention_days: number | null;
  owner_id: string;
  created_at: string;
  updated_at: string;
  permissions: CasePermissions;
}

export interface CaseList {
  items: CaseItem[];
  total: number;
}

export interface Element {
  id: string;
  position: number;
  text: string;
  source: string;
}

export interface Disclosure {
  title: string;
  technical_field: string;
  problem: string;
  solution: string;
  elements: Element[];
  content_hash: string | null;
}

export interface DisclosureInput {
  title: string;
  technical_field: string;
  problem: string;
  solution: string;
  elements: { text: string; source: "user" | "llm" | "local" }[];
}

export interface ExtractResult {
  elements: Element[];
  source: string;
  tokens: number;
  provider: string | null;
  cache_hit: boolean;
  fallback_reason: string | null;
}

export interface Job {
  id: string;
  kind: string;
  status: string;
  attempts: number;
  error: string | null;
}

export interface ProgressSnapshot {
  status: string;
  job_id: string | null;
  stage: string | null;
  case_status: string;
  attempts: number;
  error: string | null;
  tokens_used: number;
  updated_at: string;
}

export interface SearchResultItem {
  rank: number;
  patent_id: string;
  title: string | null;
  source: string | null;
  assignee: string | null;
  publication_date: string | null;
  cpc_subclasses: string[];
  url: string | null;
  score: number;
  fused_score: number | null;
  rerank_score: number | null;
  matched_chunk_ids: string[];
  excluded: boolean;
  in_chart: boolean;
}

export interface Results {
  run_id: string | null;
  suggested_cpc: unknown[];
  results: SearchResultItem[];
}

export interface Cell {
  id: string;
  element: string;
  patent_id: string;
  status: CellStatus;
  confidence: number;
  passage_id: string | null;
  excerpt: string | null;
  rationale: string | null;
  method: string;
  char_start: number | null;
  char_end: number | null;
  overridden: boolean;
  original: Record<string, unknown> | null;
  override_reason: string | null;
}

export interface Chart {
  chart_status: string | null;
  elements: Element[];
  references: string[];
  cells: Cell[];
}

export interface Risk {
  level: string | null;
  label: string | null;
  score: number | null;
  basis: string;
  anticipation_reference: string | null;
  combination: string[];
  shared_subclasses: string[];
  uncovered_elements: string[];
  per_element: Record<string, unknown>[];
  coverage: Record<string, unknown>;
  references: Record<string, unknown>[];
}

export interface ReportContent {
  title?: string;
  generated_by?: string;
  executive_summary?: string;
  closest_references?: Record<string, unknown>[];
  limitations?: string[];
  disclaimer?: string;
  risk?: { level?: string | null; label?: string | null; score?: number | null; basis?: string; uncovered_elements?: string[] };
  [key: string]: unknown;
}

export interface Report {
  state: string;
  version: number;
  content_hash: string;
  content: ReportContent;
  versions: { version: number; content_hash: string; created_at: string; approved_at: string | null }[];
  approval: Record<string, unknown> | null;
}

export interface ReviewEvent {
  id: number;
  event_type: string;
  user_id: string | null;
  cell_id: string | null;
  comment: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  user_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  ip_address: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface LlmModeInfo {
  mode: LlmMode;
  providers_configured: Record<string, boolean>;
  llm_available: boolean;
}

export interface ProviderStatus {
  name: string;
  model: string;
  configured: boolean;
  breaker: { state: string; failures: number; retry_in_seconds: number };
  minute: { tokens_used: number; tokens_limit: number; requests_used: number; requests_limit: number };
  day: {
    tokens_used: number;
    tokens_limit: number;
    tokens_percent: number;
    requests_used: number;
    requests_limit: number;
    requests_percent: number;
  };
}

export interface LlmStatus {
  mode: LlmMode;
  providers: ProviderStatus[];
}

export interface LlmSettings {
  mode: LlmMode;
  groq_model: string;
  gemini_model: string;
  defaults: { mode: LlmMode; groq_model: string; gemini_model: string };
}

export interface InviteResult {
  user: User;
  invite_token: string;
  expires_at: string;
}
