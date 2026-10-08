import type {
  ApplicationRow, Divergence, Draft, Entry, Gap, Health, Issue, KbIndex, RunDetail,
  Snapshot, StageEvent, Validation,
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

export const api = {
  health: () => request<Health>("/health"),
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

  runs: () =>
    request<{
      runs: { id: string; stages: string[]; running: boolean; complete: boolean }[];
    }>("/runs"),
  run: (id: string) => request<RunDetail>(`/runs/${id}`),
  gapReport: (id: string) => request<{ markdown: string }>(`/runs/${id}/gap-report`),

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
    request<{ turns: { role: string; text: string; clean?: boolean }[] }>(`/runs/${id}/chat`),

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
