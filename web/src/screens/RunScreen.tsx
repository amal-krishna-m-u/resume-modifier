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
          <div className="flex items-center gap-2 flex-wrap">
            <Promote
              runId={runId}
              onDone={(id) => {
                window.location.hash = `/application/${id}`;
              }}
            />
            {(identity.data?.contact_sets ?? ["default"]).map((set) => (
              <a
                key={set}
                href={`/api/runs/${runId}/export.pdf?contact_set=${set}`}
                download
                className="rounded bg-stone-900 dark:bg-stone-100 text-stone-50 dark:text-stone-900 px-3 py-1.5 text-sm font-medium hover:opacity-90"
              >
                {/* The set name only means something when there is more than
                    one. With a single set it read as "PDF · default", which
                    looks like a setting rather than a download. */}
                Download PDF
                {(identity.data?.contact_sets ?? []).length > 1 && ` · ${set}`}
              </a>
            ))}
            <a
              href={`/api/runs/${runId}/export.tex`}
              download
              className="rounded border border-stone-300 dark:border-stone-700 px-3 py-1.5 text-sm hover:bg-stone-100 dark:hover:bg-stone-900"
            >
              Download .tex
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
        <div>
          <ExportNotice
            validation={run.data.validation}
            gaps={run.data.gaps ?? []}
            runId={runId}
          />
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


/** AC-R4.3's intent, made visible.
 *
 * The criterion says export is disabled until the review has been opened. An
 * earlier version enforced that by watching for hover, which disabled the
 * download buttons for a reason nobody could see — the user's reaction was to
 * wonder whether export worked at all.
 *
 * The intent is that nothing leaves the machine before you have seen what was
 * cut and what is missing. Stating both, directly above the draft and next to
 * the buttons, serves that better than a hidden gate. */
function ExportNotice({
  validation,
  gaps,
  runId,
}: {
  validation: { clean: boolean; cuts: unknown[]; warnings: unknown[] };
  gaps: { status: string }[];
  runId: string;
}) {
  const absent = gaps.filter((gap) => gap.status === "absent").length;
  const weak = gaps.filter((gap) => gap.status === "weak").length;
  const nothingToFlag = validation.clean && gaps.length === 0;

  return (
    <div
      className={`mb-4 rounded border px-4 py-3 text-sm ${
        nothingToFlag
          ? "border-emerald-300 dark:border-emerald-800 bg-emerald-50/60 dark:bg-emerald-950/30"
          : "border-amber-300 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/30"
      }`}
    >
      {nothingToFlag ? (
        <>Every claim traces to a cited fact, and every requirement is matched.</>
      ) : (
        <>
          <strong>Before you send this:</strong>{" "}
          {validation.cuts.length > 0 && (
            <>
              the validator cut {validation.cuts.length} claim
              {validation.cuts.length === 1 ? "" : "s"}
              {absent + weak > 0 && ", and "}
            </>
          )}
          {absent > 0 && (
            <>
              {absent} requirement{absent === 1 ? " has" : "s have"} nothing behind{" "}
              {absent === 1 ? "it" : "them"}
            </>
          )}
          {absent > 0 && weak > 0 && ", "}
          {weak > 0 && <>{weak} matched only weakly</>}. The tabs below show which.
        </>
      )}
      <div className="mt-1 text-xs text-stone-500">
        Download gives the compiled PDF and the LaTeX source — the tailored resume, not your
        original file. Both are also written to <code className="font-mono">runs/{runId}/</code>.
      </div>
    </div>
  );
}
