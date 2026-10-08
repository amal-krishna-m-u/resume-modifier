import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

/** Backend, Tectonic and corpus state at a glance.
 *
 * Shows the two things that stop a run before it starts — an unavailable
 * backend and a corpus that no longer fits the context window — plus the one
 * that would publish the career record. */
export function HealthBadge() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });

  if (!health.data) return <span className="text-xs text-stone-400">…</span>;

  const { backend, corpus, render, kb } = health.data;
  const problems: string[] = [];
  if (!backend.ok) problems.push(`backend: ${backend.detail || "unavailable"}`);
  if (!corpus.fits_in_context) problems.push(`corpus exceeds context by ${corpus.shortfall}`);
  if (!render.tectonic) problems.push("tectonic not installed");
  if (corpus.parse_errors) problems.push(`${corpus.parse_errors} unparseable entries`);
  // Adding a remote to kb/ is the one action that would publish the career
  // record, and nothing in the design prevents it (OQ-9).
  if (kb.has_remote) problems.push("kb/ has a git remote — it could be published");

  const ok = problems.length === 0;

  return (
    <div
      className="flex items-center gap-2 text-xs"
      title={problems.join("\n") || `${backend.name} · ${corpus.entries} entries`}
    >
      <span className={`size-2 rounded-full ${ok ? "bg-emerald-500" : "bg-amber-500"}`} />
      <span className="hidden sm:inline text-stone-500 dark:text-stone-400 tabular-nums">
        {backend.name} · {corpus.entries} entries
      </span>
    </div>
  );
}
