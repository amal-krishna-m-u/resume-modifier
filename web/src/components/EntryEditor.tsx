import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";

type Metric = { value: string; what: string };

interface Fields {
  id: string;
  type: string;
  title: string;
  parent?: string;
  org?: string;
  location?: string;
  issuer?: string;
  url?: string;
  credential?: string;
  employment?: string;
  dates?: { start?: string; end?: string };
  tags: string[];
  metrics: Metric[];
  depth: string;
  verifiable: boolean;
  visibility: string;
  related: string[];
  order?: number | null;
  locked_phrasing?: string | null;
}

const DEPTHS = ["expert", "working", "exposure"] as const;
const VISIBILITIES = ["public", "nda", "private"] as const;

const DEPTH_HELP: Record<string, string> = {
  expert: "May be framed as deep ownership, architecture, leading the work.",
  working: "May be framed as having built and shipped it, competently.",
  exposure: "May be mentioned, never framed as expertise. This is a ceiling the writer obeys.",
};

const VISIBILITY_HELP: Record<string, string> = {
  public: "Can appear in an exported resume.",
  nda: "Selectable and visible here — it is your history — but the renderer refuses to export it.",
  private: "Never exported.",
};

/** The structured knowledge-base editor (AC-R13.1).
 *
 * Raw mode is still here, because the structured form cannot express
 * everything and an editor that blocks a legitimate edit pushes the user to
 * vim — outside the validated write path. Both modes save through the same
 * endpoint, so neither can skip validation. */
export function EntryEditor({
  type,
  id,
  onSaved,
}: {
  type: string;
  id?: string;
  onSaved?: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const creating = !id;

  const entry = useQuery({
    queryKey: ["kb", "entry", type, id],
    queryFn: () => api.entry(type, id!),
    enabled: !creating,
  });
  const taxonomy = useQuery({ queryKey: ["kb", "taxonomy"], queryFn: api.taxonomy });
  const index = useQuery({ queryKey: ["kb", "index"], queryFn: api.kbIndex });
  const history = useQuery({
    queryKey: ["kb", "history", type, id],
    queryFn: () => api.history(type, id!),
    enabled: !creating,
  });

  const [mode, setMode] = useState<"form" | "raw">("form");
  const [fields, setFields] = useState<Fields | null>(null);
  const [body, setBody] = useState("");
  const [raw, setRaw] = useState<string | null>(null);

  useEffect(() => {
    if (creating && fields === null) {
      setFields({
        id: "",
        type,
        title: "",
        tags: [],
        metrics: [],
        depth: "working",
        verifiable: true,
        visibility: "public",
        related: [],
      });
      setBody("");
      return;
    }
    if (entry.data && fields === null) {
      const front = entry.data.frontmatter as Record<string, unknown>;
      setFields({
        ...(front as unknown as Fields),
        tags: (front.tags as string[]) ?? [],
        metrics: (front.metrics as Metric[]) ?? [],
        related: (front.related as string[]) ?? [],
        depth: (front.depth as string) ?? "working",
        visibility: (front.visibility as string) ?? "public",
        verifiable: front.verifiable !== false,
      });
      setBody(entry.data.body);
      setRaw(entry.data.raw);
    }
  }, [creating, entry.data, fields, type]);

  const terms = useMemo(() => Object.keys(taxonomy.data?.terms ?? {}).sort(), [taxonomy.data]);
  const parents = useMemo(
    () =>
      (index.data?.entries ?? [])
        .filter((row) => row.type === "role" || row.type === "project")
        .map((row) => ({ id: row.id, title: row.title })),
    [index.data],
  );

  const composed = useMemo(() => {
    if (!fields) return "";
    return composeRaw(fields, body);
  }, [fields, body]);

  const save = useMutation({
    mutationFn: () => {
      const text = mode === "raw" && raw !== null ? raw : composed;
      const entryId = mode === "raw" ? (parseId(raw ?? "") ?? fields?.id ?? "") : fields!.id;
      return creating
        ? api.createEntry(type, entryId, text)
        : api.saveEntry(type, id!, text, entry.data!.hash);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kb"] });
      if (creating && fields) onSaved?.(fields.id);
      else {
        setFields(null);
        setRaw(null);
      }
    },
  });

  if (!fields) return <p className="text-sm text-stone-500">Loading…</p>;

  const failure = save.error instanceof RequestFailed ? save.error : null;
  const set = (patch: Partial<Fields>) => setFields({ ...fields, ...patch });

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="font-semibold">{creating ? `New ${type}` : id}</h2>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded border border-stone-300 dark:border-stone-700 text-xs overflow-hidden">
            {(["form", "raw"] as const).map((name) => (
              <button
                key={name}
                onClick={() => {
                  if (name === "raw") setRaw(composed);
                  setMode(name);
                }}
                className={`px-2 py-1 ${
                  mode === name ? "bg-stone-200 dark:bg-stone-800 font-medium" : ""
                }`}
              >
                {name === "form" ? "Form" : "Raw"}
              </button>
            ))}
          </div>
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || !fields.id || !fields.title}
            className="rounded bg-stone-900 dark:bg-stone-100 text-stone-50 dark:text-stone-900 px-4 py-1.5 text-sm font-medium disabled:opacity-40"
          >
            {save.isPending ? "Saving…" : creating ? "Create" : "Save"}
          </button>
        </div>
      </div>

      {mode === "raw" ? (
        <textarea
          value={raw ?? composed}
          onChange={(event) => setRaw(event.target.value)}
          spellCheck={false}
          rows={28}
          className="w-full rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 p-3 font-mono text-sm leading-relaxed"
        />
      ) : (
        <div className="space-y-4">
          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="id" hint="Permanent. Lowercase, hyphens.">
              <input
                value={fields.id}
                disabled={!creating}
                onChange={(event) => set({ id: event.target.value })}
                placeholder="ey-ase2-rag"
                className={input + (creating ? "" : " opacity-60")}
              />
            </Field>
            <Field label="title">
              <input
                value={fields.title}
                onChange={(event) => set({ title: event.target.value })}
                className={input}
              />
            </Field>
          </div>

          {type === "fact" && (
            <Field label="parent" hint="The role or project this achievement sits under.">
              <select
                value={fields.parent ?? ""}
                onChange={(event) => set({ parent: event.target.value })}
                className={input}
              >
                <option value="">—</option>
                {parents.map((parent) => (
                  <option key={parent.id} value={parent.id}>
                    {parent.title} ({parent.id})
                  </option>
                ))}
              </select>
            </Field>
          )}

          {(type === "role" || type === "project" || type === "education") && (
            <div className="grid sm:grid-cols-3 gap-3">
              <Field label={type === "education" ? "institution" : "org"}>
                <input
                  value={fields.org ?? ""}
                  onChange={(event) => set({ org: event.target.value })}
                  className={input}
                />
              </Field>
              <Field label="start" hint="YYYY-MM">
                <input
                  value={fields.dates?.start ?? ""}
                  onChange={(event) =>
                    set({ dates: { ...fields.dates, start: event.target.value } })
                  }
                  placeholder="2025-08"
                  className={input}
                />
              </Field>
              <Field label="end" hint="YYYY-MM or present">
                <input
                  value={fields.dates?.end ?? ""}
                  onChange={(event) => set({ dates: { ...fields.dates, end: event.target.value } })}
                  placeholder="present"
                  className={input}
                />
              </Field>
            </div>
          )}

          <TagPicker
            tags={fields.tags}
            terms={terms}
            aliases={taxonomy.data?.terms ?? {}}
            onChange={(tags) => set({ tags })}
          />

          <div className="grid sm:grid-cols-3 gap-3">
            <Field label="depth" hint={DEPTH_HELP[fields.depth]}>
              <select
                value={fields.depth}
                onChange={(event) => set({ depth: event.target.value })}
                className={input}
              >
                {DEPTHS.map((depth) => (
                  <option key={depth} value={depth}>
                    {depth}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="visibility" hint={VISIBILITY_HELP[fields.visibility]}>
              <select
                value={fields.visibility}
                onChange={(event) => set({ visibility: event.target.value })}
                className={input}
              >
                {VISIBILITIES.map((visibility) => (
                  <option key={visibility} value={visibility}>
                    {visibility}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="verifiable" hint="Provable if challenged.">
              <label className="flex items-center gap-2 text-sm mt-1.5">
                <input
                  type="checkbox"
                  checked={fields.verifiable}
                  onChange={(event) => set({ verifiable: event.target.checked })}
                />
                {fields.verifiable ? "yes" : "no"}
              </label>
            </Field>
          </div>

          <MetricRows metrics={fields.metrics} onChange={(metrics) => set({ metrics })} />

          <Field
            label="body"
            hint="What the selector reads. Write more here than any resume would use — detail that is not written down can never be selected."
          >
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={12}
              className={`${input} font-mono leading-relaxed`}
            />
          </Field>
        </div>
      )}

      {failure && (
        <div className="rounded border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/30 p-3 text-sm">
          <div className="font-medium text-red-800 dark:text-red-300">{failure.message}</div>
          {failure.remedy && (
            <div className="mt-1 text-red-700 dark:text-red-400">{failure.remedy}</div>
          )}
          {Array.isArray(failure.detail) && (
            <ul className="mt-2 space-y-0.5 text-xs text-red-700 dark:text-red-400">
              {failure.detail.map((problem: any, i: number) => (
                <li key={i}>
                  {problem.field ? `${problem.field}: ` : ""}
                  {problem.message ?? JSON.stringify(problem)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {save.data && save.data.warnings.length > 0 && (
        <div className="rounded border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-3 text-xs">
          {save.data.warnings.map((warning, i) => (
            <div key={i}>{warning.message}</div>
          ))}
        </div>
      )}

      {history.data && history.data.commits.length > 0 && (
        <details className="rounded border border-stone-200 dark:border-stone-800 p-3">
          <summary className="cursor-pointer text-sm font-medium">
            History ({history.data.commits.length})
          </summary>
          <ul className="mt-2 space-y-1 text-xs">
            {history.data.commits.map((commit) => (
              <li key={commit.sha} className="flex items-center gap-2">
                <code className="text-stone-400">{commit.sha.slice(0, 8)}</code>
                <span className="flex-1 truncate">{commit.message}</span>
                <button
                  onClick={async () => {
                    await api.revert(type, id!, commit.sha);
                    queryClient.invalidateQueries({ queryKey: ["kb"] });
                    setFields(null);
                  }}
                  className="text-stone-500 hover:text-stone-900 dark:hover:text-stone-100"
                >
                  revert
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

const input =
  "mt-1 w-full rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 px-2 py-1.5 text-sm";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-stone-500">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-stone-400 leading-snug">{hint}</span>}
    </label>
  );
}

/** Tag chips with autocomplete over the taxonomy, including aliases.
 *
 * Aliases matter because a posting says "vector search" where the entry is
 * tagged `rag`. Typing the posting's word should still find the term. */
function TagPicker({
  tags,
  terms,
  aliases,
  onChange,
}: {
  tags: string[];
  terms: string[];
  aliases: Record<string, { label?: string; aliases?: string[] }>;
  onChange: (tags: string[]) => void;
}) {
  const [query, setQuery] = useState("");

  const suggestions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return [];
    return terms
      .filter((term) => !tags.includes(term))
      .filter(
        (term) =>
          term.includes(needle) ||
          (aliases[term]?.label ?? "").toLowerCase().includes(needle) ||
          (aliases[term]?.aliases ?? []).some((alias) => alias.toLowerCase().includes(needle)),
      )
      .slice(0, 8);
  }, [query, terms, tags, aliases]);

  const unknown = query.trim() && !terms.includes(query.trim());

  return (
    <div>
      <span className="text-xs font-medium text-stone-500">tags</span>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {tags.map((tag) => (
          <span
            key={tag}
            className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs ${
              terms.includes(tag)
                ? "bg-stone-100 dark:bg-stone-800"
                : "bg-amber-100 dark:bg-amber-950 text-amber-900 dark:text-amber-300"
            }`}
            title={terms.includes(tag) ? undefined : "not in taxonomy.yaml yet"}
          >
            {tag}
            <button
              onClick={() => onChange(tags.filter((t) => t !== tag))}
              className="hover:text-red-600"
            >
              ×
            </button>
          </span>
        ))}
      </div>

      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && query.trim()) {
            event.preventDefault();
            onChange([...tags, suggestions[0] ?? query.trim()]);
            setQuery("");
          }
        }}
        placeholder="Add a tag — try a posting's wording, aliases are matched"
        className={input}
      />

      {suggestions.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {suggestions.map((term) => (
            <button
              key={term}
              onClick={() => {
                onChange([...tags, term]);
                setQuery("");
              }}
              className="rounded bg-stone-100 dark:bg-stone-800 px-2 py-0.5 text-xs hover:bg-stone-200 dark:hover:bg-stone-700"
            >
              {term}
              {aliases[term]?.label && (
                <span className="text-stone-400"> · {aliases[term]!.label}</span>
              )}
            </button>
          ))}
        </div>
      )}

      {unknown && suggestions.length === 0 && (
        <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">
          Not in the taxonomy. Saving still works — it becomes a warning, not an error, because
          tags describe and do not gate.
        </p>
      )}
    </div>
  );
}

/** Metrics are structured so the writer copies the figure rather than
 * restating it from prose, which is where numbers drift. */
function MetricRows({
  metrics,
  onChange,
}: {
  metrics: Metric[];
  onChange: (metrics: Metric[]) => void;
}) {
  return (
    <div>
      <span className="text-xs font-medium text-stone-500">metrics</span>
      <p className="text-[11px] text-stone-400">
        The validator cuts any number that is not here, so a figure in the body alone will not
        survive.
      </p>
      <div className="mt-1 space-y-1.5">
        {metrics.map((metric, index) => (
          <div key={index} className="flex gap-2">
            <input
              value={metric.value}
              onChange={(event) => {
                const next = [...metrics];
                next[index] = { ...metric, value: event.target.value };
                onChange(next);
              }}
              placeholder="40%"
              className={`${input} w-32 mt-0`}
            />
            <input
              value={metric.what}
              onChange={(event) => {
                const next = [...metrics];
                next[index] = { ...metric, what: event.target.value };
                onChange(next);
              }}
              placeholder="reduction in feature delivery cycle time"
              className={`${input} flex-1 mt-0`}
            />
            <button
              onClick={() => onChange(metrics.filter((_, i) => i !== index))}
              className="text-stone-400 hover:text-red-600 px-1"
            >
              ×
            </button>
          </div>
        ))}
      </div>
      <button
        onClick={() => onChange([...metrics, { value: "", what: "" }])}
        className="mt-1.5 text-xs text-stone-500 hover:text-stone-900 dark:hover:text-stone-100"
      >
        + metric
      </button>
    </div>
  );
}

/* ---------------------------------------------------------------- compose */

function yamlValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  const text = String(value);
  return /^[\w .,&()/+-]+$/.test(text) && !text.includes(": ") ? text : JSON.stringify(text);
}

/** Build the file text from the form.
 *
 * The server re-parses and re-validates this, so a mistake here is refused
 * rather than written — the form is a convenience over the same write path,
 * never a second one. */
function composeRaw(fields: Fields, body: string): string {
  const lines: string[] = [`id: ${fields.id}`, `type: ${fields.type}`];

  if (fields.parent) lines.push(`parent: ${fields.parent}`);
  lines.push(`title: ${yamlValue(fields.title)}`);
  if (fields.org) lines.push(`org: ${yamlValue(fields.org)}`);
  if (fields.location) lines.push(`location: ${yamlValue(fields.location)}`);
  if (fields.issuer) lines.push(`issuer: ${yamlValue(fields.issuer)}`);
  if (fields.credential) lines.push(`credential: ${yamlValue(fields.credential)}`);
  if (fields.url) lines.push(`url: ${yamlValue(fields.url)}`);
  if (fields.employment) lines.push(`employment: ${fields.employment}`);
  if (fields.dates?.start) {
    const end = fields.dates.end ? `, end: ${fields.dates.end}` : "";
    lines.push(`dates: {start: ${fields.dates.start}${end}}`);
  }

  lines.push(`tags: [${fields.tags.join(", ")}]`);

  const metrics = fields.metrics.filter((metric) => metric.value && metric.what);
  if (metrics.length > 0) {
    lines.push("metrics:");
    for (const metric of metrics) {
      lines.push(`  - {value: ${yamlValue(metric.value)}, what: ${yamlValue(metric.what)}}`);
    }
  }

  lines.push(`depth: ${fields.depth}`);
  lines.push(`verifiable: ${fields.verifiable}`);
  lines.push(`visibility: ${fields.visibility}`);
  if (fields.related.length > 0) lines.push(`related: [${fields.related.join(", ")}]`);
  if (fields.order != null) lines.push(`order: ${fields.order}`);
  lines.push(`locked_phrasing: ${fields.locked_phrasing ?? "null"}`);

  return `---\n${lines.join("\n")}\n---\n\n${body.trim()}\n`;
}

function parseId(raw: string): string | null {
  return raw.match(/^id:\s*(\S+)/m)?.[1] ?? null;
}
