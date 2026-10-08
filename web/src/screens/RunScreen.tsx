import { useEffect, useMemo, useState } from "react";
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
  const [showPipeline, setShowPipeline] = useState(false);

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    // While a run is in flight the artifacts on disk are the ground truth, and
    // they change between SSE frames. Polling stops once it finishes.
    refetchInterval: (query) => (query.state.data?.running ? 4000 : false),
  });
  const identity = useQuery({ queryKey: ["identity"], queryFn: api.identity });
  const kb = useQuery({ queryKey: ["kb", "index"], queryFn: api.kbIndex });

  // Seed progress from what is already on disk, so returning to a run shows
  // what happened rather than an empty panel. Token counts come from the run's
  // own usage artifact; where it has none the counts are left out rather than
  // shown as zero — an earlier version invented "0 in · 0 out" for every stage.
  useEffect(() => {
    const stages = run.data?.stages ?? [];
    if (stages.length === 0) return;
    const perAgent = run.data?.usage?.per_agent ?? {};
    setEvents((current) => {
      const seeded = { ...current };
      for (const [artifact, stage] of Object.entries(ARTIFACT_STAGE)) {
        if (stages.includes(artifact) && !seeded[stage]) {
          const used = perAgent[stage];
          seeded[stage] = {
            stage,
            status: "done",
            ...(used && {
              input: used.input_tokens ?? 0,
              output: used.output_tokens ?? 0,
              cached: used.cache_read_tokens ?? 0,
            }),
          };
        }
      }
      return seeded;
    });
  }, [run.data?.stages, run.data?.usage]);

  useEffect(() => {
    setEvents({});
    setFailure(null);
    setShowPipeline(false);

    return watchRun(runId, {
      onStage: (event) => setEvents((current) => ({ ...current, [event.stage]: event })),
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
  // Empty until identity has loaded. The preview and the download buttons
  // used to fall back to a set called "default", which does not exist for
  // anyone with named sets — so the first request after every page load was
  // for a contact set that was not there.
  const contactSets = identity.data?.contact_sets ?? [];
  const identityReady = identity.isSuccess;

  const totals = useMemo(() => {
    const all = Object.values(events);
    return {
      prompt: all.reduce((sum, e) => sum + (e.input ?? 0) + (e.cached ?? 0), 0),
      output: all.reduce((sum, e) => sum + (e.output ?? 0), 0),
      stages: all.filter((e) => e.status === "done").length,
    };
  }, [events]);

  const ready = run.data?.requirements && run.data.merged && run.data.draft && run.data.validation;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight truncate">
            {run.data?.requirements?.role_title ?? "Tailoring…"}
          </h1>
          <p className="text-xs text-stone-500 font-mono mt-0.5 truncate">{runId}</p>
        </div>

        {complete && identityReady && (
          <div className="flex items-center gap-2 flex-wrap">
            <Promote
              runId={runId}
              onDone={(id) => {
                window.location.hash = `/application/${id}`;
              }}
            />
            {contactSets.map((set) => (
              <a
                key={set}
                href={`/api/runs/${runId}/export.pdf?contact_set=${set}`}
                download
                className="btn-primary"
              >
                {/* The set name only means something when there is more than
                    one. With a single set it read as "PDF · default", which
                    looks like a setting rather than a download. */}
                Download PDF{contactSets.length > 1 && ` · ${set}`}
              </a>
            ))}
            <a href={`/api/runs/${runId}/export.tex`} download className="btn-secondary">
              .tex
            </a>
          </div>
        )}
      </div>

      {/* Full panel while the run is live. Once it is done the five stage bars
          were ~250px of prime space above the actual content, so they fold
          into one line that expands on request. */}
      {running || (!complete && Object.keys(events).length > 0) ? (
        <StageTrack events={events} running={running} />
      ) : complete && totals.stages > 0 ? (
        <div className="card">
          <button
            onClick={() => setShowPipeline(!showPipeline)}
            className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm"
          >
            <span className="text-emerald-500">●</span>
            <span className="font-medium">Pipeline complete</span>
            <span className="text-xs text-stone-500 tabular-nums">
              {totals.stages} stages
              {totals.prompt > 0 &&
                ` · ${totals.prompt.toLocaleString()} prompt · ${totals.output.toLocaleString()} output tokens`}
            </span>
            <span className="ml-auto text-xs text-stone-400">
              {showPipeline ? "hide" : "details"}
            </span>
          </button>
          {showPipeline && (
            <div className="border-t border-stone-200 dark:border-stone-800 p-4">
              <StageTrack events={events} running={false} bare />
            </div>
          )}
        </div>
      ) : null}

      {failure && (
        <div className="rounded-lg border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/40 p-4 text-sm">
          <div className="font-medium text-red-800 dark:text-red-300">{failure.message}</div>
          {failure.resumable && (
            <p className="mt-1 text-red-700 dark:text-red-400">
              Completed stages are on disk. Resume with{" "}
              <code className="font-mono">rt tailor --resume {runId}</code>
            </p>
          )}
        </div>
      )}

      {ready && run.data && identityReady && (
        <div>
          <Review
            requirements={run.data.requirements!}
            merged={run.data.merged!}
            draft={run.data.draft!}
            validation={run.data.validation!}
            gaps={run.data.gaps ?? []}
            runId={runId}
            contactSets={contactSets}
            entries={kb.data?.entries ?? []}
            version={run.dataUpdatedAt}
            chat={<Chat runId={runId} disabled={running} />}
          />
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
