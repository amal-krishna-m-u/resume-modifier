import { useCallback, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { IndexRow } from "../lib/types";
import { EntryEditor } from "../components/EntryEditor";
import { NewEntry } from "../components/NewEntry";
import { GUIDES } from "../lib/guidance";
import { byRecency, range } from "../lib/roles";

const OTHER_TYPES = ["project", "blog", "education", "certification", "award"] as const;

type View =
  | { kind: "empty" }
  | { kind: "pick" }
  | { kind: "create"; type: string; parent?: string }
  | { kind: "edit"; type: string; id: string };

const targetFor = (entry: IndexRow) => GUIDES[entry.type]?.target ?? 80;
const fill = (entry: IndexRow) => Math.min(1, entry.body_words / targetFor(entry));
const isThin = (entry: IndexRow) => entry.body_words < targetFor(entry) * 0.5;

/** Screen 6.5 — browse and edit the knowledge base (R8, R13).
 *
 * Facts nest under the role they belong to, because a role is a container and
 * the unit of selection is the achievement beneath it (spec-01 P3). Roles are
 * newest first, the way every reader scans a resume. */
export function KbBrowser() {
  const [view, setView] = useState<View>({ kind: "empty" });
  const [filter, setFilter] = useState("");

  // Whether the open editor has unsaved edits. A ref, not state: it is read
  // only at the moment of navigating away, and re-rendering on every
  // keystroke would be wasted work.
  const dirty = useRef(false);
  const onDirtyChange = useCallback((value: boolean) => {
    dirty.current = value;
  }, []);

  /** Switching entries used to discard unsaved edits without a word. */
  const go = (next: View) => {
    if (
      dirty.current &&
      !window.confirm("You have unsaved changes to this entry. Discard them?")
    ) {
      return;
    }
    dirty.current = false;
    setView(next);
  };

  const index = useQuery({ queryKey: ["kb", "index"], queryFn: api.kbIndex });
  const validation = useQuery({ queryKey: ["kb", "validate"], queryFn: api.kbValidate });
  const usage = useQuery({ queryKey: ["kb", "usage"], queryFn: api.kbUsage });

  const entries = index.data?.entries ?? [];
  const needle = filter.trim().toLowerCase();

  const matches = (entry: IndexRow) =>
    !needle ||
    entry.id.includes(needle) ||
    entry.title.toLowerCase().includes(needle) ||
    (entry.org ?? "").toLowerCase().includes(needle) ||
    entry.tags.some((tag) => tag.includes(needle));

  const roles = useMemo(
    () => entries.filter((entry) => entry.type === "role").sort(byRecency),
    [entries],
  );

  const factsByParent = useMemo(() => {
    const grouped = new Map<string, IndexRow[]>();
    for (const entry of entries.filter((e) => e.type === "fact")) {
      const parent = entry.parent ?? "(orphaned)";
      grouped.set(parent, [...(grouped.get(parent) ?? []), entry]);
    }
    return grouped;
  }, [entries]);

  const issuesByEntry = useMemo(() => {
    const grouped = new Map<string, number>();
    for (const issue of [...(validation.data?.errors ?? []), ...(validation.data?.warnings ?? [])]) {
      if (issue.entry) grouped.set(issue.entry, (grouped.get(issue.entry) ?? 0) + 1);
    }
    return grouped;
  }, [validation.data]);

  const thin = entries.filter(isThin);
  const activeId = view.kind === "edit" ? view.id : null;

  const open = (entry: IndexRow) => go({ kind: "edit", type: entry.type, id: entry.id });

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] lg:grid-cols-[22rem_minmax(0,1fr)] gap-8 items-start">
      {/* Sticky and sized to the viewport, so the list scrolls on its own
          rather than being clipped mid-row inside a fixed-height box. */}
      <aside className="space-y-3 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6.5rem)] lg:flex lg:flex-col">
        <div className="flex gap-2">
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Search title, org, tag…"
            className="field flex-1"
          />
          <button onClick={() => go({ kind: "pick" })} className="btn-primary whitespace-nowrap">
            + New
          </button>
        </div>

        {validation.data && !validation.data.ok && (
          <div className="rounded-lg border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/30 p-3 text-xs">
            <strong>{validation.data.errors.length} error(s)</strong>
            <ul className="mt-1 space-y-0.5">
              {validation.data.errors.slice(0, 4).map((issue, i) => (
                <li key={i}>
                  <button
                    className="hover:underline text-left"
                    onClick={() => {
                      const target = entries.find((e) => e.id === issue.entry);
                      if (target) open(target);
                    }}
                  >
                    {issue.entry}: {issue.message}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-stone-500 tabular-nums">
          <span>
            {entries.length} entries · {index.data?.taxonomy_terms ?? 0} tags
          </span>
          {/* Without a key the bar and dot are two unexplained marks. */}
          <span className="flex items-center gap-2 text-[10px] text-stone-400">
            <span className="flex items-center gap-1">
              <span className="inline-block h-1 w-5 rounded bg-amber-500" /> body
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block size-1.5 rounded-full bg-emerald-500" /> depth
            </span>
          </span>
        </div>

        <div className="space-y-5 overflow-y-auto pr-1 -mr-1 lg:flex-1 min-h-0">
          {roles
            .filter((role) => matches(role) || (factsByParent.get(role.id) ?? []).some(matches))
            .map((role) => (
              <div key={role.id}>
                <Row
                  entry={role}
                  strong
                  issues={issuesByEntry.get(role.id) ?? 0}
                  active={activeId === role.id}
                  onClick={() => open(role)}
                />
                <ul className="ml-3 mt-1 space-y-0.5 border-l border-stone-200 dark:border-stone-800 pl-2">
                  {(factsByParent.get(role.id) ?? []).filter(matches).map((fact) => (
                    <li key={fact.id}>
                      <Row
                        entry={fact}
                        issues={issuesByEntry.get(fact.id) ?? 0}
                        active={activeId === fact.id}
                        onClick={() => open(fact)}
                      />
                    </li>
                  ))}
                  <li>
                    <button
                      onClick={() => go({ kind: "create", type: "fact", parent: role.id })}
                      className="w-full text-left rounded px-2 py-1 text-xs text-stone-400 hover:text-stone-900 dark:hover:text-stone-100 hover:bg-stone-100 dark:hover:bg-stone-900"
                    >
                      + achievement
                    </button>
                  </li>
                </ul>
              </div>
            ))}

          {OTHER_TYPES.map((type) => {
            const rows = entries.filter((entry) => entry.type === type && matches(entry));
            if (rows.length === 0) return null;
            return (
              <div key={type}>
                <div className="px-2 text-[11px] uppercase tracking-wide text-stone-400 mb-1">
                  {GUIDES[type]?.label ?? type}
                </div>
                <ul className="space-y-0.5">
                  {rows.map((entry) => (
                    <li key={entry.id}>
                      <Row
                        entry={entry}
                        issues={issuesByEntry.get(entry.id) ?? 0}
                        active={activeId === entry.id}
                        onClick={() => open(entry)}
                      />
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}

          {needle && entries.filter(matches).length === 0 && (
            <p className="px-2 text-sm text-stone-500">Nothing matches “{filter}”.</p>
          )}
        </div>
      </aside>

      <section className="min-w-0">
        {view.kind === "pick" ? (
          <NewEntry
            onPick={(type, parent) => go({ kind: "create", type, parent })}
            onCancel={() => go({ kind: "empty" })}
          />
        ) : view.kind === "create" ? (
          <EntryEditor
            key={`new-${view.type}-${view.parent ?? ""}`}
            type={view.type}
            parent={view.parent}
            onDirtyChange={onDirtyChange}
            onSaved={(id) => {
              dirty.current = false;
              setView({ kind: "edit", type: view.type, id });
            }}
          />
        ) : view.kind === "edit" ? (
          <EntryEditor
            key={view.id}
            type={view.type}
            id={view.id}
            onDirtyChange={onDirtyChange}
            onDeleted={() => {
              dirty.current = false;
              setView({ kind: "empty" });
            }}
          />
        ) : (
          <Overview
            entries={entries}
            thin={thin}
            usage={usage.data}
            onOpen={open}
            onNew={() => go({ kind: "pick" })}
          />
        )}
      </section>
    </div>
  );
}

function Row({
  entry,
  active,
  issues,
  strong = false,
  onClick,
}: {
  entry: IndexRow;
  active: boolean;
  issues: number;
  strong?: boolean;
  onClick: () => void;
}) {
  const dates = range(entry.dates);
  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-md px-2 py-1.5 transition-colors ${
        active ? "bg-stone-200 dark:bg-stone-800" : "hover:bg-stone-100 dark:hover:bg-stone-900"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={`truncate flex-1 text-sm ${strong ? "font-medium" : ""}`}>
          {entry.title}
        </span>
        {issues > 0 && (
          <span className="text-[10px] text-amber-700 dark:text-amber-400">{issues}</span>
        )}
        {entry.visibility !== "public" && (
          <span className="text-[10px] uppercase text-amber-700 dark:text-amber-400">
            {entry.visibility}
          </span>
        )}
        <Thin entry={entry} />
        <DepthDot depth={entry.depth} />
      </div>
      {strong && (entry.org || dates) && (
        <div className="mt-0.5 text-[11px] text-stone-500 truncate">
          {[entry.org, dates].filter(Boolean).join(" · ")}
        </div>
      )}
      {!strong && (
        <div className="mt-0.5 flex gap-1.5 overflow-hidden">
          {entry.tags.slice(0, 3).map((tag) => (
            <span key={tag} className="text-[10px] text-stone-400 whitespace-nowrap">
              {tag}
            </span>
          ))}
          {entry.tags.length > 3 && (
            <span className="text-[10px] text-stone-400">+{entry.tags.length - 3}</span>
          )}
        </div>
      )}
    </button>
  );
}

/** How much body an entry has against what its type needs.
 *
 * Selection can only pick detail that exists. A one-line body is a resume
 * bullet, which is what the writer is meant to produce rather than consume, so
 * a thin entry is the most common reason a real achievement comes back
 * "matched, but not strongly". */
function Thin({ entry }: { entry: IndexRow }) {
  const f = fill(entry);
  const tone = f >= 0.5 ? "bg-emerald-500" : f > 0 ? "bg-amber-500" : "bg-stone-300";
  return (
    <span
      title={`${entry.body_words} words of body — aim for about ${targetFor(entry)}`}
      className="h-1 w-8 shrink-0 overflow-hidden rounded bg-stone-200 dark:bg-stone-800"
    >
      <span className={`block h-full ${tone}`} style={{ width: `${Math.max(f * 100, 6)}%` }} />
    </span>
  );
}

function DepthDot({ depth }: { depth: string }) {
  const tones: Record<string, string> = {
    expert: "bg-emerald-500",
    working: "bg-sky-400",
    exposure: "bg-stone-300 dark:bg-stone-600",
  };
  return (
    <span
      title={`depth: ${depth} — a ceiling on how strongly this may be framed`}
      className={`size-1.5 shrink-0 rounded-full ${tones[depth] ?? "bg-stone-300"}`}
    />
  );
}

/** What the empty pane shows.
 *
 * It used to say "Pick an entry" in small grey text beside a mostly blank
 * screen. The one thing worth knowing at this point is what to work on next,
 * so it is a prioritised list: the thinnest entries first, one click to open. */
function Overview({
  entries,
  thin,
  usage,
  onOpen,
  onNew,
}: {
  entries: IndexRow[];
  thin: IndexRow[];
  usage?: { runs: number; facts: Record<string, { runs: number; strong: number }> };
  onOpen: (entry: IndexRow) => void;
  onNew: () => void;
}) {
  // Ranked by how much real runs lean on each entry, not by thinness alone: a
  // thin internship no posting ever matches matters far less than a thin entry
  // every run selects. With no runs yet it falls back to plain thinness.
  const used = (entry: IndexRow) => usage?.facts[entry.id];
  const score = (entry: IndexRow) =>
    (1 + (used(entry)?.runs ?? 0) * 2 + (used(entry)?.strong ?? 0) * 2) * (1 - fill(entry));

  const worst = [...thin]
    .filter((entry) => entry.type === "fact" || entry.type === "project")
    .sort((a, b) => score(b) - score(a))
    .slice(0, 6);
  const ranked = (usage?.runs ?? 0) > 0;

  const facts = entries.filter((e) => e.type === "fact");
  const words = entries.reduce((sum, e) => sum + e.body_words, 0);

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Your knowledge base</h2>
        <p className="mt-1 text-sm text-stone-600 dark:text-stone-400 leading-relaxed">
          The selector reads every word of every entry against a posting. It can only pick
          detail that exists, so the quality of every tailored resume is bounded by what is
          written down here.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat value={facts.length} label="achievements" />
        <Stat value={words.toLocaleString()} label="words of detail" />
        <Stat
          value={`${entries.length - thin.length}/${entries.length}`}
          label="detailed enough"
          tone={thin.length === 0 ? "good" : "warn"}
        />
      </div>

      {worst.length > 0 ? (
        <div>
          <h3 className="text-sm font-semibold">Expand these first</h3>
          <p className="mt-0.5 text-xs text-stone-500">
            {ranked
              ? `Ranked by how often your ${usage!.runs} tailoring run${usage!.runs === 1 ? "" : "s"} selected each one, against how thin it is. `
              : ""}
            Every “matched, but not strongly” row in a gap report is a body like these: the
            work is real and the entry is too thin to carry the claim.
          </p>
          <ul className="mt-3 divide-y divide-stone-200 dark:divide-stone-800 card">
            {worst.map((entry) => (
              <li key={entry.id}>
                <button
                  onClick={() => onOpen(entry)}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-stone-50 dark:hover:bg-stone-900/60"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{entry.title}</span>
                    <span className="block truncate text-[11px] text-stone-400">
                      {used(entry)
                        ? `selected in ${used(entry)!.runs} of ${usage!.runs} run${usage!.runs === 1 ? "" : "s"}${used(entry)!.strong ? ` (${used(entry)!.strong} strongly)` : ""} · `
                        : ""}
                      {entry.body_words} of ~{targetFor(entry)} words
                    </span>
                  </span>
                  <span className="text-xs text-stone-400">Open →</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-sm text-emerald-700 dark:text-emerald-400">
          Every achievement is detailed enough to carry a claim.
        </p>
      )}

      <div className="flex gap-2">
        <button onClick={onNew} className="btn-secondary">
          + Add something new
        </button>
      </div>

      <p className="text-xs text-stone-500 leading-relaxed">
        Edits go through the same validated path as a text editor or an accepted proposal, and
        land as a commit in your local <code className="font-mono">kb/</code> repository — so
        every change can be reverted.
      </p>
    </div>
  );
}

function Stat({
  value,
  label,
  tone = "neutral",
}: {
  value: string | number;
  label: string;
  tone?: "neutral" | "good" | "warn";
}) {
  const colour =
    tone === "good"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "warn"
        ? "text-amber-600 dark:text-amber-400"
        : "";
  return (
    <div className="card px-4 py-3">
      <div className={`text-2xl font-semibold tabular-nums tracking-tight ${colour}`}>{value}</div>
      <div className="text-xs text-stone-500">{label}</div>
    </div>
  );
}
