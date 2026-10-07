import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed, watchRun } from "../lib/api";
import type { StageEvent } from "../lib/types";
import { StageTrack } from "../components/StageTrack";
import { Review } from "./Review";
import { Chat } from "../components/Chat";
import { Promote } from "../components/Promote";

/** Which stage each on-disk artifact proves finished. */
const ARTIFACT_STAGE: Record<string, string> = {
  requirements: "analyst",
  selection: "selector",
  recall: "recall",
  draft: "writer",
  validation: "validator",
};

export function RunScreen({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<Record<string, StageEvent>>({});
  const [failure, setFailure] = useState<{ message: string; resumable: boolean } | null>(null);

  // AC-R4.3: export stays disabled until the review screen has been opened.
  // The whole point of the product is that you see what was cut and what is
  // missing before anything leaves the machine.
  const [reviewed, setReviewed] = useState(false);

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    // While a run is in flight the artifacts on disk are the ground truth, and
    // they change between SSE frames. Polling stops once it finishes.
    refetchInterval: (query) => (query.state.data?.running ? 4000 : false),
  });
  const identity = useQuery({ queryKey: ["identity"], queryFn: api.identity });

  // Seed progress from the stages already on disk, so returning to a running
  // job shows what has happened rather than an empty panel. The SSE replay
  // covers the live case; this covers a server restart, a rolled buffer, and
  // the first paint before the stream connects.
  useEffect(() => {
    const stages = run.data?.stages ?? [];
    if (stages.length === 0) return;
    setEvents((current) => {
      const seeded = { ...current };
      for (const [artifact, stage] of Object.entries(ARTIFACT_STAGE)) {
        if (stages.includes(artifact) && !seeded[stage]) {
          seeded[stage] = { stage, status: "done" };
        }
      }
      return seeded;
    });
  }, [run.data?.stages]);

  useEffect(() => {
    setEvents({});
    setFailure(null);
    setReviewed(false);

    return watchRun(runId, {
      onStage: (event) => {
        setEvents((current) => ({ ...current, [event.stage]: event }));
      },
      onDone: () => {
        queryClient.invalidateQueries({ queryKey: ["run", runId] });
        queryClient.invalidateQueries({ queryKey: ["runs"] });
      },
      onError: (event) => setFailure(event),
    });
  }, [runId, queryClient]);

  // Liveness comes from the server, which owns the task. On disk a
  // half-finished run and an abandoned one look identical.
  const running = run.data?.running ?? false;
  const complete = run.data?.complete ?? false;

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {run.data?.requirements?.role_title ?? runId}
          </h1>
          <p className="text-xs text-stone-500 font-mono mt-0.5">{runId}</p>
        </div>

        {complete && (
          <div className="flex items-center gap-2">
            {!reviewed && (
              <span className="text-xs text-stone-500">Open the review to enable export</span>
            )}
            {(identity.data?.contact_sets ?? []).map((set) => (
              <a
                key={set}
                href={reviewed ? `/api/runs/${runId}/export.pdf?contact_set=${set}` : undefined}
                aria-disabled={!reviewed}
                className={`rounded border px-3 py-1.5 text-sm ${
                  reviewed
                    ? "border-stone-300 dark:border-stone-700 hover:bg-stone-100 dark:hover:bg-stone-900"
                    : "border-stone-200 dark:border-stone-800 opacity-40 pointer-events-none"
                }`}
              >
                PDF · {set}
              </a>
            ))}
            <Promote
              runId={runId}
              onDone={(id) => {
                window.location.hash = `/application/${id}`;
              }}
            />
            <a
              href={reviewed ? `/api/runs/${runId}/export.tex` : undefined}
              aria-disabled={!reviewed}
              className={`rounded border px-3 py-1.5 text-sm ${
                reviewed
                  ? "border-stone-300 dark:border-stone-700 hover:bg-stone-100 dark:hover:bg-stone-900"
                  : "border-stone-200 dark:border-stone-800 opacity-40 pointer-events-none"
              }`}
            >
              LaTeX
            </a>
          </div>
        )}
      </div>

      {(running || Object.keys(events).length > 0) && (
        <StageTrack events={events} running={running} />
      )}

      {failure && (
        <div className="rounded border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/40 p-4 text-sm">
          <div className="font-medium text-red-800 dark:text-red-300">{failure.message}</div>
          {failure.resumable && (
            <p className="mt-1 text-red-700 dark:text-red-400">
              Completed stages are on disk. Resume with{" "}
              <code className="font-mono">rt tailor --resume {runId}</code>
            </p>
          )}
        </div>
      )}

      {run.data?.requirements && run.data.merged && run.data.draft && run.data.validation && (
        <div onFocus={() => setReviewed(true)} onMouseEnter={() => setReviewed(true)}>
          <Review
            requirements={run.data.requirements}
            merged={run.data.merged}
            draft={run.data.draft}
            validation={run.data.validation}
            gaps={run.data.gaps ?? []}
          />
          <Chat runId={runId} disabled={running} />
        </div>
      )}

      {running && !complete && (
        <p className="text-sm text-sky-700 dark:text-sky-400">
          Still running. You can navigate away — progress is kept and will be here when you
          come back.
        </p>
      )}

      {!complete && !running && !failure && run.isFetched && (
        <p className="text-sm text-stone-500">
          This run stopped before finishing. Completed stages:{" "}
          {run.data?.stages.join(", ") || "none"}. Resume it with{" "}
          <code className="font-mono">rt tailor --resume {runId}</code>
        </p>
      )}
    </div>
  );
}

export { RequestFailed };
