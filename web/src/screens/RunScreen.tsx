import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

const STAGE_LABEL: Record<string, string> = {
  analyst: "reading the posting",
  selector: "selecting facts",
  recall: "second-pass recall",
  writer: "rewriting the draft",
  validator: "re-checking every claim",
};

export function RunScreen({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<Record<string, StageEvent>>({});
  const [failure, setFailure] = useState<{ message: string; resumable: boolean } | null>(null);
  const [showPipeline, setShowPipeline] = useState(false);
  const [version, setVersion] = useState(0);

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    // While a run is in flight the artifacts on disk are the ground truth, and
    // they change between SSE frames. Polling stops once it finishes.
    refetchInterval: (query) => (query.state.data?.running ? 2500 : false),
  });
  const identity = useQuery({ queryKey: ["identity"], queryFn: api.identity });
  const kb = useQuery({ queryKey: ["kb", "index"], queryFn: api.kbIndex });

  // Seed progress from what is already on disk, so returning to a run shows
  // what happened rather than an empty panel. Token counts come from the run's
  // own usage artifact; where it has none the counts are left out rather than
  // shown as zero.
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
        queryClient.invalidateQueries({ queryKey: ["chat", runId] });
      },
      onError: (event) => setFailure(event),
    });
  }, [runId, queryClient]);

  // Liveness comes from the server, which owns the task. On disk a
  // half-finished run and an abandoned one look identical.
  const running = run.data?.running ?? false;
  const complete = run.data?.complete ?? false;

  // A finished run that is running again is a revision. The review stays on
  // screen through it: it used to be replaced by the pipeline panel for the
  // whole minute or two, which is when you most want the preview in view.
  const revising = running && complete;

  // The preview only reloads when the run is quiet. Mid-revision the new draft
  // exists but has not been re-checked, so the server refuses to render it —
  // reloading then would show an error instead of the last verified resume.
  useEffect(() => {
    if (!running && run.dataUpdatedAt) setVersion(run.dataUpdatedAt);
  }, [running, run.dataUpdatedAt]);

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

  const liveStage = Object.values(events).find((e) => e.status === "running")?.stage;
  const ready = run.data?.requirements && run.data.merged && run.data.draft && run.data.validation;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <Heading
          runId={runId}
          title={run.data?.title ?? "Tailoring…"}
          company={run.data?.company ?? null}
        />
        {complete && <Promote runId={runId} onDone={(id) => (window.location.hash = `/application/${id}`)} />}
      </div>

      {/* Full panel while the first run is live. A revision gets one line, so
          the preview and conversation keep the space. */}
      {revising ? (
        <div className="card flex items-center gap-3 px-4 py-2.5 text-sm">
          <span className="size-2 animate-pulse rounded-full bg-sky-500" />
          <span className="font-medium">Revising</span>
          <span className="text-xs text-stone-500">
            {liveStage ? STAGE_LABEL[liveStage] : "working"}…
          </span>
        </div>
      ) : running || (!complete && Object.keys(events).length > 0) ? (
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
        <Review
          requirements={run.data.requirements!}
          merged={run.data.merged!}
          draft={run.data.draft!}
          validation={run.data.validation!}
          gaps={run.data.gaps ?? []}
          runId={runId}
          contactSets={contactSets}
          entries={kb.data?.entries ?? []}
          version={version}
          revising={revising}
          chat={<Chat runId={runId} running={running} />}
        />
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

/** The run's name, with a way to change it.
 *
 * What it is *called* and where it lives are different things: the folder name
 * is permanent (applications refer to it), so renaming sets a display title and
 * touches nothing else. */
function Heading({
  runId,
  title,
  company,
}: {
  runId: string;
  title: string;
  company: string | null;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);

  const rename = useMutation({
    mutationFn: (value: string) => api.renameRun(runId, { title: value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      setEditing(false);
    },
  });

  const date = runId.slice(0, 10);
  const failure = rename.error instanceof RequestFailed ? rename.error : null;

  return (
    <div className="min-w-0">
      {editing ? (
        <div className="flex items-center gap-2">
          <input
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && draft.trim()) rename.mutate(draft.trim());
              if (event.key === "Escape") setEditing(false);
            }}
            className="field text-lg font-semibold w-[min(32rem,80vw)]"
          />
          <button
            onClick={() => rename.mutate(draft.trim())}
            disabled={rename.isPending}
            className="btn-primary"
          >
            Save
          </button>
          <button onClick={() => setEditing(false)} className="btn-ghost">
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2 group">
          <h1 className="text-xl font-semibold tracking-tight truncate">{title}</h1>
          <button
            onClick={() => {
              setDraft(title);
              setEditing(true);
            }}
            className="btn-ghost text-xs opacity-0 group-hover:opacity-100 focus:opacity-100"
            title="Rename — changes the label, not the folder"
          >
            Rename
          </button>
        </div>
      )}
      <p className="mt-0.5 truncate text-xs text-stone-500">
        {[company, date].filter(Boolean).join(" · ")}
        <span className="ml-2 font-mono text-stone-400">{runId}</span>
      </p>
      {failure && <p className="text-xs text-red-700 dark:text-red-400">{failure.message}</p>}
    </div>
  );
}
