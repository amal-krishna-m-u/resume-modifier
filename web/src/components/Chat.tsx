import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";
import { Inline } from "../lib/inline";
import type { DraftChange, RevisionTurn } from "../lib/types";

const STARTERS = [
  "Shorten the summary",
  "Move the strongest match to the top",
  "Remove the weakest bullet",
];

/** Revise the resume by conversation (R5).
 *
 * Every turn re-enters the pipeline at the Writer and **always** re-runs the
 * Validator (AC-R5.2): chat cannot bypass validation, or "just add that I led
 * the team" writes an unsupported claim straight into the document.
 *
 * The answers show what *actually* changed. The model's own account is a claim,
 * so beside it is a diff computed from the two drafts — and the validator's
 * cuts, with reasons, where you asked for the change rather than on another
 * tab. Until now the reply to every request was "draft revised". */
export function Chat({ runId, running }: { runId: string; running: boolean }) {
  const [message, setMessage] = useState("");
  const queryClient = useQueryClient();
  const scroller = useRef<HTMLDivElement>(null);
  const lastTurn = useRef<HTMLDivElement>(null);

  const history = useQuery({
    queryKey: ["chat", runId],
    queryFn: () => api.chatHistory(runId),
    // The revision runs on the server. Polling while it does means the answer
    // appears even if you navigated away and came back.
    refetchInterval: running ? 1500 : false,
  });

  const send = useMutation({
    mutationFn: () => api.chat(runId, message.trim()),
    onSuccess: () => {
      setMessage("");
      queryClient.invalidateQueries({ queryKey: ["chat", runId] });
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  const turns = history.data?.turns ?? [];
  const failure = send.error instanceof RequestFailed ? send.error : null;
  const canSend = message.trim().length > 0 && !running && !send.isPending;

  // A new answer scrolls to its START. Scrolling to the bottom put the model's
  // own account — the first thing worth reading — above the fold behind the
  // list of changes. Done on the container directly: scrollIntoView would also
  // scroll the page.
  useEffect(() => {
    const box = scroller.current;
    if (!box) return;
    const last = turns[turns.length - 1];
    box.scrollTop =
      last?.role === "assistant" && lastTurn.current
        ? lastTurn.current.offsetTop - box.offsetTop - 4
        : box.scrollHeight;
  }, [turns.length, running]);

  return (
    <section className="flex flex-col">
      <p className="text-xs text-stone-500 leading-relaxed">
        Ask for changes in plain words. Every revision re-checks every claim, so a request that
        needs a fact you have not recorded gets cut with a reason — the cue to add the fact, not
        to re-ask.
      </p>
      <p className="mt-1.5 text-xs text-stone-500 leading-relaxed">
        This changes the <em>resume</em> only. To change your knowledge base itself, use{" "}
        <a href="#/kb" className="underline">Knowledge base → Add by chat</a>.
      </p>

      <div
        ref={scroller}
        className="relative mt-4 space-y-4 overflow-y-auto pr-1"
        style={{ maxHeight: "calc(100vh - 27rem)", minHeight: "6rem" }}
      >
        {turns.length === 0 && !running && (
          <div className="flex flex-wrap gap-2">
            {STARTERS.map((starter) => (
              <button key={starter} onClick={() => setMessage(starter)} className="btn-secondary text-xs">
                {starter}
              </button>
            ))}
          </div>
        )}

        {turns.map((turn, index) => (
          <div key={index} ref={index === turns.length - 1 ? lastTurn : undefined}>
            <Turn turn={turn} />
          </div>
        ))}

        {running && (
          <div className="flex items-center gap-2 text-xs text-sky-700 dark:text-sky-400">
            <span className="size-1.5 animate-pulse rounded-full bg-sky-500" />
            Rewriting the draft, then re-checking every claim against your facts…
          </div>
        )}
      </div>

      <div className="mt-3 space-y-2 border-t border-stone-200 dark:border-stone-800 pt-3">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && canSend) send.mutate();
          }}
          disabled={running}
          rows={3}
          placeholder="Lead with the trading engine; drop the award bullet"
          className="field resize-none disabled:opacity-50"
        />
        <div className="flex items-center justify-between gap-3">
          <span className="text-[11px] text-stone-400">
            {running ? "Revising — the preview updates when it's done." : "⌘↵ to send"}
          </span>
          <button onClick={() => send.mutate()} disabled={!canSend} className="btn-primary">
            {send.isPending ? "Sending…" : "Send"}
          </button>
        </div>
        {failure && (
          <p className="text-xs text-red-700 dark:text-red-400">
            {failure.message} {failure.remedy}
          </p>
        )}
      </div>
    </section>
  );
}

function Turn({ turn }: { turn: RevisionTurn }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[88%] rounded-lg rounded-br-sm bg-stone-900 px-3 py-2 text-sm text-stone-50 dark:bg-stone-100 dark:text-stone-900 whitespace-pre-wrap">
          {turn.text}
        </div>
      </div>
    );
  }

  const changes = turn.changes ?? [];
  const cuts = turn.cuts ?? [];
  const warnings = turn.warnings ?? [];

  return (
    <div className="space-y-2.5">
      <div className="max-w-[94%] rounded-lg rounded-bl-sm bg-stone-100 dark:bg-stone-900 px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap">
        {turn.text}
      </div>

      {changes.length > 0 && <Changes changes={changes} />}

      {cuts.length > 0 && (
        <div className="rounded-lg border border-red-200 dark:border-red-900 bg-red-50/60 dark:bg-red-950/20 px-3 py-2.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-red-800 dark:text-red-300">
            The validator cut {cuts.length} claim{cuts.length === 1 ? "" : "s"}
          </div>
          <ul className="mt-1.5 space-y-2 text-xs">
            {cuts.map((cut, i) => (
              <li key={i}>
                <div className="text-stone-500 line-through decoration-red-400/70">
                  <Inline text={cut.bullet} />
                </div>
                <div className="mt-0.5 text-red-900 dark:text-red-300">{cut.reason}</div>
                {cut.replacement && (
                  <div className="mt-0.5 text-stone-700 dark:text-stone-300">
                    Now reads: <Inline text={cut.replacement} />
                  </div>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-stone-500">
            A cut usually means a real fact is missing from your knowledge base. Add it in the
            Knowledge base tab and ask again.
          </p>
        </div>
      )}

      {warnings.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50/60 dark:bg-amber-950/20 px-3 py-2 text-xs text-amber-900 dark:text-amber-300">
          {warnings.map((warning, i) => (
            <li key={i}>
              {warning.kind && <strong className="font-medium">{warning.kind}: </strong>}
              {warning.reason}
            </li>
          ))}
        </ul>
      )}

      {turn.clean === true && cuts.length === 0 && warnings.length === 0 && (
        <p className="text-[11px] text-emerald-600 dark:text-emerald-400">
          ● Every claim traces to a recorded fact.
        </p>
      )}
    </div>
  );
}

/** What changed, from the two drafts — not from the model's own account. */
function Changes({ changes }: { changes: DraftChange[] }) {
  const [open, setOpen] = useState(changes.length <= 3);
  return (
    <div className="rounded-lg border border-stone-200 dark:border-stone-800">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-xs"
      >
        <span className="font-medium">
          {changes.length} change{changes.length === 1 ? "" : "s"} to the draft
        </span>
        <span className="text-stone-400">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <ul className="space-y-2.5 border-t border-stone-200 dark:border-stone-800 p-3">
          {changes.map((change, i) => (
            <li key={i} className="text-xs">
              <Change change={change} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Change({ change }: { change: DraftChange }) {
  const str = (value: unknown) => (typeof value === "string" ? value : "");

  if (change.kind === "reordered") {
    return <span className="text-stone-600 dark:text-stone-400">The order of the bullets changed.</span>;
  }
  if (change.kind === "skills") {
    return <span className="text-stone-600 dark:text-stone-400">The skills section was regrouped.</span>;
  }

  const label = {
    summary: "Summary rewritten",
    added: "Added",
    removed: "Removed",
    changed: "Reworded",
  }[change.kind];

  return (
    <div className="space-y-1">
      <div className="font-medium">
        {label}
        {change.lead ? <span className="font-normal text-stone-500"> · {change.lead}</span> : null}
      </div>
      {str(change.before) && (
        <p className="rounded bg-red-50 dark:bg-red-950/20 px-2 py-1 leading-relaxed text-stone-600 dark:text-stone-400">
          <Inline text={str(change.before)} />
        </p>
      )}
      {str(change.after) && (
        <p className="rounded bg-emerald-50 dark:bg-emerald-950/20 px-2 py-1 leading-relaxed">
          <Inline text={str(change.after)} />
        </p>
      )}
    </div>
  );
}
