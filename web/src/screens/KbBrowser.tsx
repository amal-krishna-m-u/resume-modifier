import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { IndexRow } from "../lib/types";
import { EntryEditor } from "../components/EntryEditor";

const TYPE_ORDER = [
  "role", "fact", "project", "blog", "education", "certification", "award",
] as const;

/** Screen 6.5 — browse and edit the knowledge base (R8, R13).
 *
 * Facts are shown nested under the role they belong to, because that is how
 * they are actually organised: a role is a container and the unit of selection
 * is the achievement beneath it (spec-01 P3). A flat list made that invisible.
 */
export function KbBrowser() {
  const [selected, setSelected] = useState<{ type: string; id: string } | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const index = useQuery({ queryKey: ["kb", "index"], queryFn: api.kbIndex });
  const validation = useQuery({ queryKey: ["kb", "validate"], queryFn: api.kbValidate });

  const entries = index.data?.entries ?? [];
  const needle = filter.trim().toLowerCase();

  const matches = (entry: IndexRow) =>
    !needle ||
    entry.id.includes(needle) ||
    entry.title.toLowerCase().includes(needle) ||
    entry.tags.some((tag) => tag.includes(needle));

  // Facts hang off their parent; everything else is grouped by type.
  const roles = entries.filter((entry) => entry.type === "role");
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

  return (
    <div className="grid lg:grid-cols-[24rem_1fr] gap-8 items-start">
      <aside className="space-y-3">
        <div className="flex gap-2">
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Search id, title or tag"
            className="flex-1 rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 px-3 py-2 text-sm"
          />
          <select
            value=""
            onChange={(event) => {
              if (event.target.value) {
                setCreating(event.target.value);
                setSelected(null);
              }
            }}
            className="rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 px-2 text-sm"
          >
            <option value="">+ New</option>
            {TYPE_ORDER.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>

        {validation.data && !validation.data.ok && (
          <div className="rounded border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/30 p-3 text-xs">
            <strong>{validation.data.errors.length} error(s)</strong>
            <ul className="mt-1 space-y-0.5">
              {validation.data.errors.slice(0, 4).map((issue, i) => (
                <li key={i}>
                  <button
                    className="hover:underline text-left"
                    onClick={() =>
                      issue.entry &&
                      setSelected({
                        type: entries.find((e) => e.id === issue.entry)?.type ?? "fact",
                        id: issue.entry,
                      })
                    }
                  >
                    {issue.entry}: {issue.message}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="text-xs text-stone-500 tabular-nums">
          {entries.length} entries · {(index.data?.estimated_corpus_tokens ?? 0).toLocaleString()}{" "}
          est. tokens · {index.data?.taxonomy_terms ?? 0} tags
        </div>

        <div className="space-y-4 max-h-[36rem] overflow-y-auto pr-1">
          {roles.filter((role) => matches(role) || (factsByParent.get(role.id) ?? []).some(matches))
            .map((role) => (
              <div key={role.id}>
                <Row
                  entry={role}
                  issues={issuesByEntry.get(role.id) ?? 0}
                  active={selected?.id === role.id}
                  onClick={() => {
                    setSelected({ type: role.type, id: role.id });
                    setCreating(null);
                  }}
                />
                <ul className="ml-3 mt-1 space-y-0.5 border-l border-stone-200 dark:border-stone-800 pl-2">
                  {(factsByParent.get(role.id) ?? []).filter(matches).map((fact) => (
                    <li key={fact.id}>
                      <Row
                        entry={fact}
                        issues={issuesByEntry.get(fact.id) ?? 0}
                        active={selected?.id === fact.id}
                        onClick={() => {
                          setSelected({ type: fact.type, id: fact.id });
                          setCreating(null);
                        }}
                      />
                    </li>
                  ))}
                </ul>
              </div>
            ))}

          {TYPE_ORDER.filter((type) => type !== "role" && type !== "fact").map((type) => {
            const rows = entries.filter((entry) => entry.type === type && matches(entry));
            if (rows.length === 0) return null;
            return (
              <div key={type}>
                <div className="text-[11px] uppercase tracking-wide text-stone-400 mb-1">
                  {type}
                </div>
                <ul className="space-y-0.5">
                  {rows.map((entry) => (
                    <li key={entry.id}>
                      <Row
                        entry={entry}
                        issues={issuesByEntry.get(entry.id) ?? 0}
                        active={selected?.id === entry.id}
                        onClick={() => {
                          setSelected({ type: entry.type, id: entry.id });
                          setCreating(null);
                        }}
                      />
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </aside>

      {creating ? (
        <EntryEditor key={`new-${creating}`} type={creating} onSaved={(id) => {
          setCreating(null);
          setSelected({ type: creating, id });
        }} />
      ) : selected ? (
        <EntryEditor key={selected.id} type={selected.type} id={selected.id} />
      ) : (
        <Empty />
      )}
    </div>
  );
}

function Row({
  entry,
  active,
  issues,
  onClick,
}: {
  entry: IndexRow;
  active: boolean;
  issues: number;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded px-2 py-1 text-sm ${
        active ? "bg-stone-200 dark:bg-stone-800" : "hover:bg-stone-100 dark:hover:bg-stone-900"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="truncate flex-1">{entry.title}</span>
        {issues > 0 && (
          <span className="text-[10px] text-amber-700 dark:text-amber-400">{issues}</span>
        )}
        {entry.visibility !== "public" && (
          <span className="text-[10px] uppercase text-amber-700 dark:text-amber-400">
            {entry.visibility}
          </span>
        )}
        <DepthDot depth={entry.depth} />
      </div>
      <div className="flex gap-1 mt-0.5">
        {entry.tags.slice(0, 4).map((tag) => (
          <span key={tag} className="text-[10px] text-stone-400">
            {tag}
          </span>
        ))}
        {entry.tags.length > 4 && (
          <span className="text-[10px] text-stone-400">+{entry.tags.length - 4}</span>
        )}
      </div>
    </button>
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
      className={`size-1.5 rounded-full shrink-0 ${tones[depth] ?? "bg-stone-300"}`}
    />
  );
}

function Empty() {
  return (
    <div className="text-sm text-stone-600 dark:text-stone-400 max-w-xl space-y-3">
      <p>Pick an entry, or create one.</p>
      <p className="text-xs text-stone-500 leading-relaxed">
        Edits go through the same validated path as a text editor or an accepted proposal, and
        land as a commit in your local <code className="font-mono">kb/</code> repository — so
        every change is revertable.
      </p>
      <p className="text-xs text-stone-500 leading-relaxed">
        The bodies are what the selector reads. They should hold more detail than any resume
        would use: detail that is not written down can never be selected, and the gap report's
        &ldquo;matched, but not strongly&rdquo; rows are almost always a thin body rather than
        a missing fact.
      </p>
    </div>
  );
}
