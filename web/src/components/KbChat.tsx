import { LiveTrace } from "./LiveTrace";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";
import type { IndexRow, KbChatTurn } from "../lib/types";
import { ProposalCard } from "./ProposalCard";

/** Update the knowledge base by talking about it.
 *
 * The assistant never writes. It proposes; each proposal is shown as exactly
 * what would change, with its validation result, and only Accept saves it —
 * through the same validated path as the form and the raw editor. So this is a
 * faster way to *draft* an entry, never a way around the checks.
 *
 * One conversation per entry, plus one for the knowledge base as a whole:
 * "add that this handled 2,000 users" only means something beside the entry it
 * is about. */
export function KbChat({
  scope,
  focus,
  entries,
  heading,
  starters,
  seed,
  blockedReason,
  onOpenEntry,
}: {
  scope: string;
  focus?: Record<string, unknown>;
  entries: IndexRow[];
  heading: string;
  starters: { label: string; text: string }[];
  seed?: string;
  /** Why accepting is held up, e.g. unsaved edits in the Form tab. */
  blockedReason?: string | null;
  onOpenEntry?: (type: string, id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState(seed ?? "");
  const scroller = useRef<HTMLDivElement>(null);
  const lastTurn = useRef<HTMLDivElement>(null);

  const chat = useQuery({
    queryKey: ["kbchat", scope],
    queryFn: () => api.kbChat(scope),
    // The assistant works in the background on the server. Polling while it
    // does means a reply shows up even if you navigated away and came back —
    // run progress had exactly that bug once.
    refetchInterval: (query) => (query.state.data?.running ? 1500 : false),
  });

  const turns = chat.data?.turns ?? [];
  const running = chat.data?.running ?? false;

  const send = useMutation({
    mutationFn: () => api.kbChatSend(scope, message.trim(), focus),
    onSuccess: () => {
      setMessage("");
      queryClient.invalidateQueries({ queryKey: ["kbchat", scope] });
    },
  });

  const reset = useMutation({
    mutationFn: () => api.kbChatReset(scope),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kbchat", scope] }),
  });

  const acceptedIds = useMemo(
    () =>
      new Set(
        turns.flatMap((turn) =>
          (turn.proposals ?? []).filter((p) => p.status === "accepted").map((p) => p.entry_id),
        ),
      ),
    [turns],
  );

  // A new answer scrolls to its start, so the reply and its questions are read
  // before the proposal cards below them.
  useEffect(() => {
    const box = scroller.current;
    if (!box) return;
    const last = turns[turns.length - 1];
    box.scrollTop =
      last?.role === "assistant" && lastTurn.current
        ? lastTurn.current.offsetTop - box.offsetTop - 4
        : box.scrollHeight;
  }, [turns.length, running]);

  const failure = send.error instanceof RequestFailed ? send.error : null;
  const canSend = message.trim().length > 0 && !running && !send.isPending;
  const pending = turns.flatMap((t) => t.proposals ?? []).filter((p) => p.status === "pending");

  return (
    <div className="flex h-full min-h-[28rem] flex-col">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{heading}</h3>
          <p className="mt-0.5 text-xs text-stone-500 leading-relaxed">
            Describe what you did, in your own words. The assistant proposes changes and asks
            for what it is missing — it never invents details. <strong className="font-medium">
            Nothing is saved until you accept.</strong>
          </p>
        </div>
        {turns.length > 0 && (
          <button
            onClick={() => reset.mutate()}
            disabled={running || reset.isPending}
            className="btn-ghost text-xs shrink-0"
            title="Archives this conversation and starts a new one"
          >
            Start over
          </button>
        )}
      </div>

      <div
        ref={scroller}
        className="relative mt-4 flex-1 space-y-4 overflow-y-auto pr-1"
        style={{ maxHeight: "calc(100vh - 21rem)" }}
      >
        {turns.length === 0 && !running && (
          <div className="space-y-3">
            <p className="text-xs text-stone-500">Not sure where to start? Try one of these:</p>
            <div className="flex flex-wrap gap-2">
              {starters.map((starter) => (
                <button
                  key={starter.label}
                  onClick={() => setMessage(starter.text)}
                  className="btn-secondary text-xs"
                >
                  {starter.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, index) => (
          <div
            key={`${turn.at ?? index}-${index}`}
            ref={index === turns.length - 1 ? lastTurn : undefined}
          >
            <Turn
              turn={turn}
              scope={scope}
              entries={entries}
              acceptedIds={acceptedIds}
              blockedReason={blockedReason}
              onOpenEntry={onOpenEntry}
            />
          </div>
        ))}

        {running && (
          <div className="flex items-center gap-2 text-xs text-sky-700 dark:text-sky-400">
            <span className="size-1.5 animate-pulse rounded-full bg-sky-500" />
            Reading your knowledge base and working out what to propose…
          </div>
        )}
        {running && <LiveTrace traceKey={`kb-chat:${scope}`} defaultOpen onlyWhileActive />}
      </div>

      {pending.length > 1 && (
        <p className="mt-2 text-[11px] text-stone-400">
          {pending.length} proposals are waiting. Review each; accept the ones you want.
        </p>
      )}

      <div className="mt-3 space-y-2 border-t border-stone-200 dark:border-stone-800 pt-3">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && canSend) send.mutate();
          }}
          disabled={running}
          rows={3}
          placeholder={
            turns.length === 0
              ? "e.g. At EY I also built an evaluation harness for the RAG pipeline…"
              : "Answer its questions, or ask for a change…"
          }
          className="field resize-none disabled:opacity-50"
        />
        <div className="flex items-center justify-between gap-3">
          <span className="text-[11px] text-stone-400">
            {running ? "Working — you can leave this page; the reply will be here." : "⌘↵ to send"}
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
    </div>
  );
}

function Turn({
  turn,
  scope,
  entries,
  acceptedIds,
  blockedReason,
  onOpenEntry,
}: {
  turn: KbChatTurn;
  scope: string;
  entries: IndexRow[];
  acceptedIds: Set<string>;
  blockedReason?: string | null;
  onOpenEntry?: (type: string, id: string) => void;
}) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[88%] rounded-lg rounded-br-sm bg-stone-900 px-3 py-2 text-sm text-stone-50 dark:bg-stone-100 dark:text-stone-900 whitespace-pre-wrap">
          {turn.text}
        </div>
      </div>
    );
  }

  if (turn.error) {
    return (
      <div className="rounded-lg border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/30 p-3 text-xs text-red-800 dark:text-red-300">
        <div className="font-medium">That didn't work.</div>
        <p className="mt-0.5 break-words">{turn.error}</p>
        <p className="mt-1 text-red-700/80 dark:text-red-400/80">
          Nothing was saved. You can send your message again.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {turn.text && (
        <div className="max-w-[92%] rounded-lg rounded-bl-sm bg-stone-100 dark:bg-stone-900 px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap">
          {turn.text}
        </div>
      )}

      {turn.questions && turn.questions.length > 0 && (
        <div className="rounded-lg border border-sky-200 dark:border-sky-900 bg-sky-50/60 dark:bg-sky-950/20 px-3 py-2.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-sky-800 dark:text-sky-300">
            It needs to know
          </div>
          <ul className="mt-1.5 space-y-1 text-sm">
            {turn.questions.map((question, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-sky-500">?</span>
                {question}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(turn.proposals ?? []).map((proposal) => (
        <ProposalCard
          key={proposal.id}
          proposal={proposal}
          scope={scope}
          entries={entries}
          acceptedIds={acceptedIds}
          blockedReason={blockedReason}
          onOpenEntry={onOpenEntry}
        />
      ))}
    </div>
  );
}
