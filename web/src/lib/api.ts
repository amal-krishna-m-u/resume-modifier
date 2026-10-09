import type {
  ApplicationRow, Divergence, Draft, Entry, FitMatch, Gap, Health, Issue, KbIndex, RunDetail,
  KbChatTurn, Proposal, RevisionTurn, RunSummary, Snapshot, StageEvent, Validation,
} from "./types";

export class RequestFailed extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly remedy: string,
    readonly detail: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    // The server sends {code, message, detail, remedy} for everything it
    // refuses (spec-04 §8). Surfacing `remedy` is the whole point — a status
    // code alone tells the user nothing they can act on.
    let body: { code?: string; message?: string; remedy?: string; detail?: unknown } = {};
    try {
      body = await response.json();
    } catch {
      body = { message: await response.text() };
    }
    throw new RequestFailed(
      response.status,
      body.code ?? "unknown",
      body.message ?? response.statusText,
      body.remedy ?? "",
      body.detail,
    );
  }

  return response.json() as Promise<T>;
}

export interface BackendInfo {
  name: string;
  label: string;
  blurb: string;
  login: string | null;
  models: string[];
}
export interface Settings {
  backend: string;
  effective_backend: string;
  env_override: boolean;
  models: Record<string, string>;
  openai_compat: { base_url: string; model: string; api_key_env: string; context_tokens: number };
  backends: BackendInfo[];
  file: string | null;
}
export interface BackendTest {
  ok: boolean;
  detail?: string;
  credential?: string;
  login: string | null;
  window?: number;
  fits?: boolean;
}

export interface Observability {
  show_reasoning: boolean;
  local_log: boolean;
  record_content: boolean;
  langfuse: { enabled: boolean; host: string; keys_set: boolean; refused: string | null };
  summary: {
    agent: string;
    prompt_version: string;
    backend: string;
    calls: number;
    errors: number;
    mean_seconds: number;
    mean_output_tokens: number;
  }[];
  evals: {
    name: string;
    label: string;
    backend: string;
    mean: Record<string, number>;
    reviewed_cases: number;
  }[];
}

export const api = {
  observability: () => request<Observability>("/observability"),
  health: () => request<Health>("/health"),
  settings: () => request<Settings>("/settings"),
  saveSettings: (body: Partial<Pick<Settings, "backend" | "models" | "openai_compat">> & {
      observability?: { show_reasoning?: boolean };
    }) =>
    request<Settings>("/settings", { method: "PUT", body: JSON.stringify(body) }),
  testBackend: (backend: string, model?: string) =>
    request<BackendTest>("/settings/test", {
      method: "POST",
      body: JSON.stringify({ backend, model }),
    }),
  identity: () =>
    request<{ configured: boolean; contact_sets: string[]; default_set?: string }>("/identity"),

  kbIndex: () => request<KbIndex>("/kb/index"),
  kbValidate: () =>
    request<{ ok: boolean; errors: Issue[]; warnings: Issue[] }>("/kb/validate"),
  entry: (type: string, id: string) => request<Entry>(`/kb/${type}/${id}`),

  kbUsage: () =>
    request<{ runs: number; facts: Record<string, { runs: number; strong: number }> }>(
      "/kb/usage",
    ),

  taxonomy: () =>
    request<{
      terms: Record<string, { label?: string; facet?: string; aliases?: string[] }>;
      hash: string;
    }>("/taxonomy"),

  saveEntry: (type: string, id: string, raw: string, baseHash: string) =>
    request<{ hash: string; commit: string | null; warnings: Issue[] }>(`/kb/${type}/${id}`, {
      method: "PUT",
      body: JSON.stringify({ id, raw, base_hash: baseHash }),
    }),

  createEntry: (type: string, id: string, raw: string) =>
    request<{ hash: string; commit: string | null; warnings: Issue[] }>(`/kb/${type}`, {
      method: "POST",
      body: JSON.stringify({ id, raw }),
    }),

  deleteEntry: (type: string, id: string) =>
    request<{ deleted: string }>(`/kb/${type}/${id}`, { method: "DELETE" }),

  dryRun: (type: string, id: string, raw: string) =>
    request<{ ok: boolean; errors: unknown[] }>("/kb/validate", {
      method: "POST",
      body: JSON.stringify({ type, id, raw }),
    }),

  history: (type: string, id: string) =>
    request<{ commits: { sha: string; message: string; when: string; author: string }[] }>(
      `/kb/${type}/${id}/history`,
    ),

  revert: (type: string, id: string, sha: string) =>
    request<{ hash: string }>(`/kb/${type}/${id}/revert`, {
      method: "POST",
      body: JSON.stringify({ sha }),
    }),

  runs: () => request<{ runs: RunSummary[] }>("/runs"),
  run: (id: string) => request<RunDetail>(`/runs/${id}`),

  renameRun: (id: string, patch: { title?: string | null; company?: string | null }) =>
    request<{ id: string; title: string; company: string | null }>(`/runs/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  gapReport: (id: string) => request<{ markdown: string }>(`/runs/${id}/gap-report`),

  fit: (text: string) =>
    request<{ matches: FitMatch[]; library_size: number }>("/fit", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  fitFill: (text: string, runId: string) =>
    request<{ run_id: string }>("/fit/fill", {
      method: "POST",
      body: JSON.stringify({ text, run_id: runId }),
    }),

  startRun: (text: string, company?: string, role?: string) =>
    request<{ run_id: string }>("/runs", {
      method: "POST",
      body: JSON.stringify({ text, company, role }),
    }),

  chat: (id: string, message: string) =>
    request<{ run_id: string }>(`/runs/${id}/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  chatHistory: (id: string) =>
    request<{ turns: RevisionTurn[] }>(`/runs/${id}/chat`),

  // -- knowledge-base chat ---------------------------------------------------
  kbChat: (scope: string) =>
    request<{ turns: KbChatTurn[]; running: boolean; scope: string }>(
      `/kb/chat?scope=${encodeURIComponent(scope)}`,
    ),

  kbChatSend: (scope: string, message: string, focus?: Record<string, unknown>) =>
    request<{ running: boolean }>("/kb/chat", {
      method: "POST",
      body: JSON.stringify({ scope, message, focus }),
    }),

  kbChatAccept: (scope: string, proposalId: string) =>
    request<{ proposal: Proposal }>(
      `/kb/chat/proposals/${proposalId}/accept?scope=${encodeURIComponent(scope)}`,
      { method: "POST" },
    ),

  kbChatReject: (scope: string, proposalId: string) =>
    request<{ proposal: Proposal }>(
      `/kb/chat/proposals/${proposalId}/reject?scope=${encodeURIComponent(scope)}`,
      { method: "POST" },
    ),

  kbChatReset: (scope: string) =>
    request<{ archived: string | null }>(`/kb/chat?scope=${encodeURIComponent(scope)}`, {
      method: "DELETE",
    }),

  promote: (runId: string, body: Record<string, unknown>) =>
    request<{ id: string; directory: string; rendered: string[] }>(`/runs/${runId}/promote`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  applications: (filters: { liveOnly?: boolean; status?: string; company?: string } = {}) => {
    const query = new URLSearchParams();
    if (filters.liveOnly) query.set("live_only", "true");
    if (filters.status) query.set("status", filters.status);
    if (filters.company) query.set("company", filters.company);
    const suffix = query.toString() ? `?${query}` : "";
    return request<{ applications: ApplicationRow[]; pipeline: Record<string, number> }>(
      `/applications${suffix}`,
    );
  },

  application: (id: string) =>
    request<{ application: Record<string, any>; files: string[] }>(`/applications/${id}`),

  applicationSnapshot: (id: string) =>
    request<{ snapshot: Snapshot; divergence: Divergence[] }>(`/applications/${id}/snapshot`),

  verifyApplication: (id: string) =>
    request<{ id: string; intact: boolean; problems: { file: string; issue: string }[] }>(
      `/applications/${id}/verify`,
    ),

  patchApplication: (id: string, patch: Record<string, unknown>) =>
    request<{ application: Record<string, unknown> }>(`/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
};

export type { Draft, Gap, Validation };

/** Subscribe to a run's stage events. Returns an unsubscribe function. */
export function watchRun(
  runId: string,
  handlers: {
    onStage?: (event: StageEvent) => void;
    onDone?: (event: { clean: boolean; revision?: boolean }) => void;
    onError?: (event: { message: string; resumable: boolean }) => void;
  },
): () => void {
  const source = new EventSource(`/api/runs/${runId}/events`);
  const on = <T,>(name: string, handler?: (event: T) => void) => {
    if (handler) {
      source.addEventListener(name, (event) =>
        handler(JSON.parse((event as MessageEvent).data) as T),
      );
    }
  };
  on("stage", handlers.onStage);
  on("done", handlers.onDone);
  on("error", handlers.onError);
  return () => source.close();
}

/** Subscribe to knowledge-base file changes (AC-R8.2). */
export function watchKb(onChange: (event: { path: string; kind: string }) => void): () => void {
  const source = new EventSource("/api/events");
  source.addEventListener("kb-change", (event) =>
    onChange(JSON.parse((event as MessageEvent).data)),
  );
  return () => source.close();
}
