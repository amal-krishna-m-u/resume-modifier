import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";

/** Screen 6.1. Paste the posting and go. */
export function NewRun({
  onStarted,
  onOpen,
}: {
  onStarted: (runId: string) => void;
  onOpen: (runId: string) => void;
}) {
  const [text, setText] = useState("");
  const [company, setCompany] = useState("");

  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const index = useQuery({ queryKey: ["kb", "index"], queryFn: api.kbIndex });

  const start = useMutation({
    mutationFn: () => api.startRun(text.trim(), company.trim() || undefined),
    onSuccess: (result) => onStarted(result.run_id),
  });

  const words = text.trim().split(/\s+/).filter(Boolean).length;
  const tokens = index.data?.estimated_corpus_tokens ?? 0;
  const recent = (runs.data?.runs ?? []).filter((run) => run.stages.length > 0).slice(0, 8);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,44rem)_1fr] gap-12 items-start">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Tailor to a posting</h1>
        <p className="mt-2 text-stone-600 dark:text-stone-400 leading-relaxed">
          Paste the job description. Five agents read your whole knowledge base against it and
          report what matched, what didn't, and what they cut.
        </p>

        <label className="mt-6 flex items-baseline justify-between text-sm font-medium" htmlFor="posting">
          <span>Job description</span>
          {words > 0 && (
            <span className="text-xs font-normal text-stone-400 tabular-nums">{words} words</span>
          )}
        </label>
        <textarea
          id="posting"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && text.trim()) {
              start.mutate();
            }
          }}
          rows={15}
          autoFocus
          placeholder="Paste the full posting — responsibilities and requirements both. The analyst reads what a posting implies as well as what it lists."
          className="field mt-2 font-mono leading-relaxed"
        />

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div className="w-full max-w-xs">
            <label className="block text-sm font-medium" htmlFor="company">
              Company <span className="text-stone-400 font-normal">(optional)</span>
            </label>
            <input
              id="company"
              value={company}
              onChange={(event) => setCompany(event.target.value)}
              className="field mt-2"
              placeholder="Used in the run's folder name"
            />
          </div>
          <button
            onClick={() => start.mutate()}
            disabled={!text.trim() || start.isPending}
            className="btn-primary px-5 py-2"
          >
            {start.isPending ? "Starting…" : "Run the pipeline"}
            <span className="kbd hidden sm:inline">⌘↵</span>
          </button>
        </div>

        {/* Setting expectations: a run is minutes, not seconds, and it uses the
            subscription's rate limit. Better said before than discovered. */}
        <p className="mt-3 text-xs text-stone-500 leading-relaxed">
          Takes about two to three minutes. Reads your knowledge base
          {tokens > 0 && ` (~${tokens.toLocaleString()} tokens)`} in full, twice — once for each
          selection pass — so a bigger knowledge base costs proportionally more. You can leave
          the page; progress is kept.
        </p>

        {start.error instanceof RequestFailed && (
          <div className="mt-4 rounded-lg border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/40 p-3 text-sm">
            <div className="font-medium text-red-800 dark:text-red-300">{start.error.message}</div>
            {start.error.remedy && (
              <div className="mt-1 text-red-700 dark:text-red-400">{start.error.remedy}</div>
            )}
          </div>
        )}
      </div>

      <aside>
        <h2 className="text-sm font-semibold">Recent runs</h2>
        {recent.length === 0 ? (
          <p className="mt-2 text-sm text-stone-500">Nothing yet. Your first run will appear here.</p>
        ) : (
          <ul className="mt-3 card divide-y divide-stone-200 dark:divide-stone-800">
            {recent.map((run) => {
              const date = run.id.slice(0, 10);
              const rest = run.id.slice(11).replace(/-/g, " ");
              return (
                <li key={run.id}>
                  <button
                    onClick={() => onOpen(run.id)}
                    className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-stone-50 dark:hover:bg-stone-900/60"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm capitalize">{rest || run.id}</span>
                      <span className="block text-[11px] text-stone-400 tabular-nums">{date}</span>
                    </span>
                    <State running={run.running} complete={run.complete} />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </aside>
    </div>
  );
}

function State({ running, complete }: { running: boolean; complete: boolean }) {
  if (running) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-sky-600 dark:text-sky-400">
        <span className="size-1.5 animate-pulse rounded-full bg-sky-500" /> running
      </span>
    );
  }
  return complete ? (
    <span className="text-xs text-emerald-600 dark:text-emerald-400">done</span>
  ) : (
    <span className="text-xs text-amber-600 dark:text-amber-400">stopped</span>
  );
}
