import type { StageEvent } from "../lib/types";

const STAGES = ["analyst", "selector", "recall", "writer", "validator"] as const;

/** Screen 6.2. Live stage status with token counts.
 *
 * Selector and Recall render side by side because they run concurrently, and
 * the visual pairing is what communicates that they are two independent passes
 * rather than a sequence. */
export function StageTrack({
  events,
  running,
  bare = false,
}: {
  events: Record<string, StageEvent>;
  running: boolean;
  /** Without the outer card and title, for embedding in another panel. */
  bare?: boolean;
}) {
  const total = Object.values(events).reduce(
    (sum, event) => sum + (event.input ?? 0) + (event.cached ?? 0),
    0,
  );
  const output = Object.values(events).reduce((sum, event) => sum + (event.output ?? 0), 0);

  return (
    <div className={bare ? "" : "card p-4"}>
      {!bare && (
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">
            Pipeline {running && <span className="text-stone-400 font-normal">· running</span>}
          </h2>
          {total > 0 && (
            <span className="text-xs tabular-nums text-stone-500">
              {total.toLocaleString()} prompt · {output.toLocaleString()} output
            </span>
          )}
        </div>
      )}

      <div className={`${bare ? "" : "mt-3"} grid gap-2`}>
        <Stage event={events.analyst} name="analyst" label="Analyst" />
        <div className="grid grid-cols-2 gap-2">
          <Stage event={events.selector} name="selector" label="Selector" />
          <Stage event={events.recall} name="recall" label="Recall" />
        </div>
        <Stage event={events.writer} name="writer" label="Writer" />
        <Stage event={events.validator} name="validator" label="Validator" />
      </div>

      <p className="mt-3 text-xs text-stone-500">
        Selector and Recall run concurrently and both read every fact in full.
      </p>
    </div>
  );
}

function Stage({
  event,
  name,
  label,
}: {
  event: StageEvent | undefined;
  name: (typeof STAGES)[number];
  label: string;
}) {
  const status = event?.status;
  const tone =
    status === "done"
      ? "border-emerald-300 dark:border-emerald-800 bg-emerald-50/60 dark:bg-emerald-950/30"
      : status === "running"
        ? "border-sky-300 dark:border-sky-800 bg-sky-50/60 dark:bg-sky-950/30 animate-pulse"
        : status === "skipped"
          ? "border-stone-200 dark:border-stone-800 opacity-60"
          : "border-stone-200 dark:border-stone-800 opacity-40";

  return (
    <div className={`rounded border px-3 py-2 text-sm ${tone}`} data-stage={name}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{label}</span>
        {status === "done" && event && hasCounts(event) && (
          <span className="text-xs tabular-nums text-stone-500">
            {((event.input ?? 0) + (event.cached ?? 0)).toLocaleString()} in ·{" "}
            {(event.output ?? 0).toLocaleString()} out
            {event.repairs ? ` · ${event.repairs} repair` : ""}
          </span>
        )}
        {status === "skipped" && (
          <span className="text-xs text-stone-500">{event?.reason ?? "skipped"}</span>
        )}
      </div>
    </div>
  );
}

/** A stage seeded from disk has no usage unless the run recorded it. Showing
 * zeros there is wrong rather than empty, so absent counts are left out. */
function hasCounts(event: StageEvent): boolean {
  return event.input !== undefined || event.output !== undefined || event.cached !== undefined;
}
