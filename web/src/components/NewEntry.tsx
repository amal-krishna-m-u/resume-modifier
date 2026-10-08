import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { GUIDES } from "../lib/guidance";
import { byRecency } from "../lib/roles";

const ORDER = [
  "fact", "role", "project", "blog", "education", "certification", "award",
] as const;

/** Picking what to add.
 *
 * Deliberately not a dropdown of schema type names. "fact" means nothing until
 * you know the schema, and the distinction that actually matters — a job is a
 * container, an achievement is the thing that gets selected — is invisible in
 * a list of nouns.
 *
 * Achievements come first because most of a knowledge base should be those,
 * and because it is the one people under-create.
 */
export function NewEntry({
  onPick,
  onCancel,
}: {
  onPick: (type: string, parent?: string) => void;
  onCancel: () => void;
}) {
  const index = useQuery({ queryKey: ["kb", "index"], queryFn: api.kbIndex });
  const counts = index.data?.counts ?? {};
  const roles = (index.data?.entries ?? [])
    .filter((entry) => entry.type === "role")
    .sort(byRecency);

  const factsPerRole = roles.length > 0 ? (counts.fact ?? 0) / roles.length : 0;

  return (
    <div className="max-w-2xl space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="font-semibold">What are you adding?</h2>
        <button onClick={onCancel} className="text-sm text-stone-500 hover:underline">
          Cancel
        </button>
      </div>

      {roles.length > 0 && factsPerRole < 4 && (
        <p className="rounded border border-sky-200 dark:border-sky-900 bg-sky-50/60 dark:bg-sky-950/30 px-3 py-2 text-xs text-sky-900 dark:text-sky-300">
          {counts.fact ?? 0} achievements across {roles.length} roles is about{" "}
          {factsPerRole.toFixed(1)} each. Every achievement you do not record is one the
          pipeline can never select.
        </p>
      )}

      <div className="grid gap-2">
        {ORDER.map((type) => {
          const guide = GUIDES[type]!;
          return (
            <button
              key={type}
              onClick={() => onPick(type)}
              className="text-left rounded border border-stone-200 dark:border-stone-800 p-3 hover:border-stone-400 dark:hover:border-stone-600 hover:bg-stone-50 dark:hover:bg-stone-900/50"
            >
              <div className="flex items-baseline gap-2">
                <span className="font-medium text-sm">{guide.label}</span>
                <code className="text-[11px] text-stone-400">{type}</code>
                {counts[type] ? (
                  <span className="ml-auto text-xs text-stone-400">{counts[type]} so far</span>
                ) : (
                  <span className="ml-auto text-xs text-stone-400">none yet</span>
                )}
              </div>
              <p className="mt-1 text-xs text-stone-500 leading-relaxed">{guide.blurb}</p>
            </button>
          );
        })}
      </div>

      {roles.length > 0 && (
        <div>
          <p className="text-xs font-medium text-stone-500">
            Or add an achievement straight to a role
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {roles.map((role) => (
              <button
                key={role.id}
                onClick={() => onPick("fact", role.id)}
                className="rounded bg-stone-100 dark:bg-stone-800 px-2 py-1 text-xs hover:bg-stone-200 dark:hover:bg-stone-700"
              >
                + {role.title}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
