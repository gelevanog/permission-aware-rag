// Typed client for the Clearance API. Every call carries the bearer token of the user it is made for.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export interface DemoUser {
  email: string;
  name: string;
  title: string;
  department: string;
  idp_groups: string[];
  persona: string;
}

export interface Me {
  subject: string;
  email: string;
  name: string;
  principals: string[];
  groups: string[];
  is_admin: boolean;
  title: string | null;
}

export interface Citation {
  number: number;
  chunk_id: string;
  document_id: string;
  title: string;
  path: string;
  section: string;
  snippet: string;
  score: number;
  source_url: string | null;
}

export interface RetrievedItem {
  number: number | null;
  document_id: string;
  title: string;
  section: string;
  score: number;
  in_context: boolean;
}

export interface DocSummary {
  id: string;
  title: string;
  path: string;
}

export interface Trace {
  principals: string[];
  searchable_documents: number;
  excluded_documents: number | null;
  searchable: DocSummary[];
  retrieved: RetrievedItem[];
  below_threshold: number;
  timings_ms: Record<string, number>;
  model: string;
  cache_hit: boolean;
  fallback: string | null;
}

export interface Answer {
  text: string;
  outcome: "answered" | "no_answer";
  citations: Citation[];
  trace: Trace;
}

export interface Health {
  status: string;
  documents: number;
  model: string;
  model_is_local: boolean;
  local_only: boolean;
  embedding_model: string;
  auth_mode: string;
}

export interface SectionRule {
  heading: string;
  allow: string[];
  deny: string[];
}

export interface Acl {
  allow: string[];
  deny: string[];
  sections: SectionRule[];
}

export interface AdminDocument {
  id: string;
  title: string;
  path: string;
  source: string;
  external_id: string;
  acl: Acl;
  acl_version: number;
  chunks: number;
  headings: string[];
  updated_at: string;
}

export interface DirectoryUser extends DemoUser {
  principals: string[];
  unmapped_groups: string[];
}

export interface Directory {
  company: string;
  users: DirectoryUser[];
  groups: { name: string; idp_group: string; description: string }[];
}

export interface AclUpdateResult {
  document_id: string;
  chunks_updated: number;
  acl_version: number;
  elapsed_ms: number;
}

export interface AuditEntry {
  id: number;
  ts: string;
  event: string;
  actor: string;
  principals_hash: string;
  question_hash: string | null;
  question_preview: string | null;
  retrieved_document_ids: string[];
  cited_document_ids: string[];
  candidates_excluded: number | null;
  outcome: string;
  model: string | null;
  cache_hit: boolean;
  latency_ms: number | null;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  users: () => request<DemoUser[]>("/dev-idp/users"),
  token: (email: string) =>
    request<{ id_token: string; expires_in: number }>("/dev-idp/token", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  me: (token: string) => request<Me>("/api/me", {}, token),
  documents: (token: string) => request<{ documents: DocSummary[]; excluded: number | null }>("/api/documents", {}, token),
  ask: (token: string, question: string) =>
    request<Answer>("/api/ask", { method: "POST", body: JSON.stringify({ question }) }, token),
  adminDocuments: (token: string) => request<AdminDocument[]>("/api/admin/documents", {}, token),
  adminDirectory: (token: string) => request<Directory>("/api/admin/directory", {}, token),
  updateAcl: (token: string, id: string, acl: Acl) =>
    request<AclUpdateResult>(`/api/admin/documents/${id}/acl`, { method: "PUT", body: JSON.stringify(acl) }, token),
  resync: (token: string) =>
    request<Record<string, number | string[]>>("/api/admin/resync", { method: "POST" }, token),
  audit: (token: string) => request<AuditEntry[]>("/api/admin/audit?limit=300", {}, token),
  evaluation: (token: string) => request<EvalResults>("/api/eval", {}, token),
};

export type StreamEvent =
  | { type: "trace"; trace: Trace }
  | { type: "token"; text: string }
  | { type: "replace"; text: string }
  | { type: "done"; answer: Answer }
  | { type: "error"; error: string };

/** POST /api/ask/stream and call `onEvent` for every server-sent event. */
export async function streamAsk(
  token: string,
  question: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_URL}/api/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!response.ok || !response.body) throw new ApiError(response.status, response.statusText);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as StreamEvent);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

// ---- evaluation results (results/*.json, served by /api/eval) --------------------------------------------
export interface LatencySummary {
  n: number;
  p50: number | null;
  p95: number | null;
  mean: number | null;
  max: number | null;
}

export interface LeakSystem {
  pairs: number;
  pairs_with_restricted_chunk_in_context: number;
  restricted_chunks_in_context: number;
  pairs_with_hidden_canary_in_context: number;
  context_leak_rate: number | null;
  pairs_with_hidden_canary_in_answer?: number;
  answer_leak_rate?: number | null;
  distinct_generations?: number;
}

export interface RecallStudyRow {
  restricted_copies: number;
  documents_added: number;
  k: number;
  pairs: number;
  recall_clearance: number | null;
  recall_postfilter: number | null;
  empty_postfilter: number;
  answers_lost_by_postfilter: number;
}

export interface QualitySummary {
  answerable: number;
  correct: number;
  correctness: number | null;
  judged: number;
  faithfulness: number | null;
  expect_met: number | null;
  false_refusals: number;
  answered_with_citation: number | null;
  unanswerable: number;
  unanswerable_declined: number;
  generate_ms: LatencySummary;
  errors: number;
}

export interface EvalResults {
  leak: {
    date: string;
    generator: string | null;
    systems: Record<string, LeakSystem>;
    postfilter_recall?: { systems: Record<string, { recall_at_k: number | null; mean_context_chunks: number | null }> };
    postfilter_recall_study?: RecallStudyRow[];
    users: number;
    questions: number;
  } | null;
  quality: {
    date: string;
    judge: string | null;
    retrieval: { questions: number; recall_at_k: number | null; mrr: number | null };
    generators: Record<string, { model: string; summary: QualitySummary }>;
  } | null;
  acl_change: {
    date: string;
    revocations: {
      trials: number;
      excluded_on_next_query: number;
      excluded_under_rls_only: number;
      embeddings_computed: number;
      acl_update_ms: LatencySummary;
      next_query_ms: LatencySummary;
    };
    deletions: { trials: number; gone_on_next_query: number; delete_ms: LatencySummary; reingest_with_embedding_ms: LatencySummary };
  } | null;
  latency: Record<string, unknown> | null;
  smoke: { date: string; smoke: { model: string; ok: boolean; error?: string }[] } | null;
  calls_summary: { total_requests: number; all_model_ids_free: boolean; served_models: Record<string, number> } | null;
}
