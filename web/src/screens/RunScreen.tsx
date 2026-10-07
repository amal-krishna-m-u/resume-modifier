import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed, watchRun } from "../lib/api";
import type { StageEvent } from "../lib/types";
import { StageTrack } from "../components/StageTrack";
import { Review } from "./Review";
import { Chat } from "../components/Chat";
import { Promote } from "../components/Promote";

export function RunScreen({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<Record<string, StageEvent>>({});
  const [running, setRunning] = useState(false);
  const [failure, setFailure] = useState<{ message: string; resumable: boolean } | null>(null);

  // AC-R4.3: export stays disabled until the review screen has been opened.
  // The whole point of the product is that you see what was cut and what is
  // missing before anything leaves the machine.
  const [reviewed, setReviewed] = useState(false);

  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId) });
  const identity = useQuery({ queryKey: ["identity"], queryFn: api.identity });

  const seenStages = useRef(false);

  useEffect(() => {
    setEvents({});
    setFailure(null);
    setReviewed(false);
    seenStages.current = false;

    return watchRun(runId, {
      onStage: (event) => {
        seenStages.current = true;
        setRunning(event.status === "running" || event.stage !== "validator");
        setEvents((current) => ({ ...current, [event.stage]: event }));
      },
      onDone: () => {
        setRunning(false);
        queryClient.invalidateQueries({ queryKey: ["run", runId] });
        queryClient.invalidateQueries({ queryKey: ["runs"] });
      },
      onError: (event) => {
        setRunning(false);
        setFailure(event);
      },
    });
  }, [runId, queryClient]);

  const complete = run.data?.stages.includes("validation") ?? false;

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

      {!complete && !running && !failure && run.isFetched && (
        <p className="text-sm text-stone-500">
          This run has not finished. Completed stages: {run.data?.stages.join(", ") || "none"}.
        </p>
      )}
    </div>
  );
}

export { RequestFailed };
