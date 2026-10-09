import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";
import type { FitMatch } from "../lib/types";

/** Screen 6.1. Paste the posting. Fit an existing resume first; only then
 * spend five agents on a shape you have not written for yet. */
export function NewRun({
  onStarted,
  onOpen,
  onOpenApplication,
}: {
  onStarted: (runId: string) => void;
  onOpen: (runId: string) => void;
  onOpenApplication: (id: string) => void;
}) {
  const [text, setText] = useState("");
  const [company, setCompany] = useState("");
  const [debounced, setDebounced] = useState("");

  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const index = useQuery({ queryKey: ["kb", "index"], queryFn: api.kbIndex });

  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(text.trim()), 450);
    return () => window.clearTimeout(handle);
  }, [text]);

  const words = text.trim().split(/\s+/).filter(Boolean).length;
  const canFit = debounced.split(/\s+/).filter(Boolean).length >= 40;

  const fitted = useQuery({
    queryKey: ["fit", debounced],
    queryFn: () => api.fit(debounced),
    enabled: canFit,
  });

  const start = useMutation({
    mutationFn: () => api.startRun(text.trim(), company.trim() || undefined),
    onSuccess: (result) => onStarted(result.run_id),
  });
  const fill = useMutation({
    mutationFn: (runId: string) => api.fitFill(text.trim(), runId),
    onSuccess: (result) => onStarted(result.run_id),
  });

  const tokens = index.data?.estimated_corpus_tokens ?? 0;
  const recent = (runs.data?.runs ?? []).filter((run) => run.stages.length > 0).slice(0, 8);
  const best = fitted.data?.matches[0];
  const busy = start.isPending || fill.isPending;
  const failed =
    start.error instanceof RequestFailed
      ? start.error
      : fill.error instanceof RequestFailed
        ? fill.error
        : null;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,44rem)_1fr] gap-12 items-start">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Tailor to a posting</h1>
        <p className="mt-2 text-stone-600 dark:text-stone-400 leading-relaxed">
          Paste the job description. The tool first looks for a resume you already built for
          this shape of role. A new five-agent run is only for a posting that does not fit.
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

        {canFit && fitted.isFetching && (
          <p className="mt-3 text-xs text-stone-500">Looking through resumes you already have…</p>
        )}

        {best && <FitCard match={best} library={fitted.data?.library_size ?? 0} />}

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
          {best?.recommend && best.run_id ? (
            <>
              <button
                onClick={() => onOpen(best.run_id!)}
                className="btn-primary px-5 py-2"
              >
                Use this resume
              </button>
              <button
                onClick={() => fill.mutate(best.run_id!)}
                disabled={busy}
                className="btn-secondary px-5 py-2"
              >
                {fill.isPending ? "Updating…" : "Fill the gaps"}
              </button>
              <button
                onClick={() => start.mutate()}
                disabled={!text.trim() || busy}
                className="btn-secondary px-5 py-2"
              >
                New tailor anyway
              </button>
            </>
          ) : best?.recommend && best.kind === "application" ? (
            <>
              <button
                onClick={() => onOpenApplication(best.id)}
                className="btn-primary px-5 py-2"
              >
                Use this resume
              </button>
              {best.run_id ? (
                <button
                  onClick={() => fill.mutate(best.run_id!)}
                  disabled={busy}
                  className="btn-secondary px-5 py-2"
                >
                  {fill.isPending ? "Updating…" : "Fill the gaps"}
                </button>
              ) : (
                <button
                  onClick={() => start.mutate()}
                  disabled={!text.trim() || busy}
                  className="btn-secondary px-5 py-2"
                >
                  Tailor a new version
                </button>
              )}
            </>
          ) : (
            <button
              onClick={() => start.mutate()}
              disabled={!text.trim() || start.isPending}
              className="btn-primary px-5 py-2"
            >
              {start.isPending ? "Starting…" : "Run the pipeline"}
              <span className="kbd hidden sm:inline">⌘↵</span>
            </button>
          )}
        </div>

        <p className="mt-3 text-xs text-stone-500 leading-relaxed">
          Fit is local and free. Filling gaps revises the existing draft (Writer + Validator).
          A full pipeline reads your knowledge base
          {tokens > 0 && ` (~${tokens.toLocaleString()} tokens)`} in full, twice.
        </p>

        {failed && (
          <div className="mt-4 rounded-lg border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/40 p-3 text-sm">
            <div className="font-medium text-red-800 dark:text-red-300">{failed.message}</div>
            {failed.remedy && (
              <div className="mt-1 text-red-700 dark:text-red-400">{failed.remedy}</div>
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
              return (
                <li key={run.id}>
                  <button
                    onClick={() => onOpen(run.id)}
                    className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-stone-50 dark:hover:bg-stone-900/60"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{run.title}</span>
                      <span className="block truncate text-[11px] text-stone-400 tabular-nums">
                        {[run.company, date].filter(Boolean).join(" · ")}
                      </span>
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

function FitCard({ match, library }: { match: FitMatch; library: number }) {
  const score = Math.round(match.score * 100);
  return (
    <div className="mt-4 card p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-stone-500">
            {match.recommend ? "Reuse this resume" : "Closest resume — a new tailor is safer"}
          </p>
          <p className="mt-0.5 font-medium">{match.title}</p>
          <p className="text-xs text-stone-500">
            {[match.company, match.kind, `${score}% match`].filter(Boolean).join(" · ")}
            {library > 1 && ` · ${library} in the library`}
          </p>
        </div>
      </div>
      {match.absent.length > 0 && (
        <GapList
          title="This resume does not cover"
          items={match.absent}
          tone="text-red-800 dark:text-red-300"
        />
      )}
      {match.weak.length > 0 && (
        <GapList
          title="Thin on"
          items={match.weak}
          tone="text-amber-800 dark:text-amber-300"
        />
      )}
      {match.absent.length === 0 && match.weak.length === 0 && (
        <p className="text-sm text-stone-600 dark:text-stone-400">
          No local gaps against this posting. Open the resume, or retarget wording with Fill
          the gaps.
        </p>
      )}
    </div>
  );
}

function GapList({
  title,
  items,
  tone,
}: {
  title: string;
  items: { text: string }[];
  tone: string;
}) {
  return (
    <div>
      <p className={`text-xs font-medium ${tone}`}>{title}</p>
      <ul className="mt-1 space-y-1 text-sm text-stone-700 dark:text-stone-300">
        {items.slice(0, 6).map((item) => (
          <li key={item.text} className="leading-snug">
            {item.text}
          </li>
        ))}
        {items.length > 6 && (
          <li className="text-xs text-stone-400">{items.length - 6} more</li>
        )}
      </ul>
    </div>
  );
}

function State({ running, complete }: { running: boolean; complete: boolean }) {
  if (running) {
    return <span className="text-[11px] text-sky-700 dark:text-sky-400">running</span>;
  }
  if (complete) {
    return <span className="text-[11px] text-stone-400">done</span>;
  }
  return <span className="text-[11px] text-amber-700 dark:text-amber-400">partial</span>;
}
