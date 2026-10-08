// Mirrors the server's shapes. Hand-written rather than generated: the API is
// small, and a generator would add a build step for types that change when the
// Python dataclasses do anyway.

export type Depth = "expert" | "working" | "exposure";
export type Visibility = "public" | "nda" | "private";
export type ChosenBy = "both" | "selector" | "recall";

export interface ApiError {
  code: string;
  message: string;
  detail: unknown;
  remedy: string;
}

export interface IndexRow {
  id: string;
  type: string;
  title: string;
  tags: string[];
  parent: string | null;
  depth: Depth;
  visibility: Visibility;
  verifiable: boolean;
  dates: { start: string; end?: string } | null;
  metrics: number;
  estimated_tokens: number;
  body_words: number;
  path: string;
  sha256: string;
}

export interface KbIndex {
  counts: Record<string, number>;
  estimated_corpus_tokens: number;
  taxonomy_terms: number;
  skills: number;
  entries: IndexRow[];
}

export interface Entry {
  id: string;
  type: string;
  frontmatter: Record<string, unknown>;
  body: string;
  raw: string;
  hash: string;
  path: string;
}

export interface Issue {
  level: "error" | "warning";
  code: string;
  message: string;
  entry: string | null;
  field: string | null;
}

export interface Health {
  backend: {
    name: string;
    ok: boolean;
    credential: string;
    detail: string;
    window: number;
    overhead: number;
    cost: string;
  };
  render: { tectonic: boolean; version: string | null; cache_warm: boolean };
  corpus: {
    entries: number;
    estimated_tokens: number;
    fits_in_context: boolean;
    shortfall: number;
    parse_errors: number;
  };
  kb: { versioned: boolean; has_remote: boolean };
}

export interface Requirement {
  id: string;
  text: string;
  kind: "required" | "preferred" | "implicit";
  source?: "explicit" | "inferred";
  quote?: string;
}

export interface SelectedFact {
  fact_id: string;
  chosen_by: ChosenBy;
  requirement_ids: string[];
  strength: "strong" | "moderate" | "weak";
  reason: string | null;
  argument: string | null;
  depth: Depth | null;
}

export interface Merged {
  facts: SelectedFact[];
  considered_and_rejected: { fact_id: string; reason: string }[];
  tag_proposals: { fact_id: string; add_tags: string[]; why?: string }[];
  counts: {
    total: number;
    both: number;
    selector_only: number;
    recall_only: number;
    rejected: number;
  };
}

export interface Bullet {
  lead?: string;
  text: string;
  sources: string[];
  metrics_used?: string[];
}

export interface Draft {
  summary?: string;
  summary_sources?: string[];
  sections: { kind: string; role_id?: string; bullets: Bullet[] }[];
  skills?: { group: string; items: string[]; sources: string[] }[];
}

export interface Validation {
  verdict: "clean" | "changes_made";
  clean: boolean;
  cuts: { bullet: string; section?: string; reason: string; replacement?: string | null }[];
  warnings: { bullet: string; section?: string; kind?: string; reason: string }[];
}

export interface Gap {
  requirement_id: string;
  text: string;
  kind: string;
  status: "absent" | "weak";
  matched: string[];
  confirmed_by_both?: string[];
}

export interface RunDetail {
  id: string;
  stages: string[];
  running?: boolean;
  complete?: boolean;
  posting?: string;
  requirements?: { role_title?: string; seniority?: string; requirements: Requirement[] };
  merged?: Merged;
  draft?: Draft;
  validation?: Validation;
  gaps?: Gap[];
  usage?: { total: Record<string, number>; per_agent: Record<string, Record<string, number>> };
}

export type StageStatus = "running" | "done" | "skipped";

export interface StageEvent {
  stage: string;
  status: StageStatus;
  input?: number;
  output?: number;
  cached?: number;
  repairs?: number;
  reason?: string;
}

export interface ApplicationRow {
  id: string;
  company: string;
  company_slug: string;
  role: string;
  job_id: string | null;
  applied_on: string;
  status: string;
  referral_received: number;
  referrer: string | null;
  contact_set_sent: string | null;
  run_id: string | null;
  last_stage_on: string | null;
}

export interface Divergence {
  fact_id: string;
  status: "changed" | "deleted" | "added-since";
  sent?: string;
  current?: string;
}

export interface Snapshot {
  frozen_at: string;
  run_id: string;
  template_version: string;
  summary?: string;
  bullets: { lead?: string; text: string; sources: string[] }[];
  facts_as_sent: { id: string; body?: string; sha256?: string }[];
}
