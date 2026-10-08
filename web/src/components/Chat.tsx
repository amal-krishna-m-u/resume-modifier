import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";

/** Screen 6.4. Revision by conversation (R5).
 *
 * Every turn re-enters the pipeline at the Writer and **always** re-runs the
 * Validator (AC-R5.2). Chat cannot bypass validation, or "just add that I led
 * the team" writes an unsupported claim straight into the document. */
export function Chat({ runId, disabled }: { runId: string; disabled: boolean }) {
  const [message, setMessage] = useState("");
  const queryClient = useQueryClient();

  const history = useQuery({
    queryKey: ["chat", runId],
    queryFn: () => api.chatHistory(runId),
  });

  const send = useMutation({
    mutationFn: () => api.chat(runId, message.trim()),
    onSuccess: () => {
      setMessage("");
      queryClient.invalidateQueries({ queryKey: ["chat", runId] });
    },
  });

  const turns = history.data?.turns ?? [];

  return (
    <section className="card p-4">
      <h2 className="text-sm font-semibold">Revise</h2>
      <p className="mt-1 text-xs text-stone-500 leading-relaxed">
        Ask for changes in plain words. Every revision re-runs the validator, so a request
        that needs a fact you have not recorded gets cut with a reason — the cue to add the
        fact, not to re-ask.
      </p>

      {turns.length > 0 && (
        <ul className="mt-4 space-y-2">
          {turns.map((turn, index) => (
            <li
              key={index}
              className={`text-sm rounded px-3 py-2 ${
                turn.role === "user"
                  ? "bg-stone-100 dark:bg-stone-900"
                  : "text-stone-500 text-xs"
              }`}
            >
              {turn.text}
              {turn.clean === false && (
                <span className="ml-2 text-amber-700 dark:text-amber-400">
                  — the validator made changes
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 space-y-2">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && message.trim() && !disabled) {
              send.mutate();
            }
          }}
          disabled={disabled || send.isPending}
          rows={3}
          placeholder="Lead with the trading engine; drop the award bullet"
          className="field resize-none disabled:opacity-50"
        />
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-stone-400">
            {send.isPending || disabled ? "Revising — this takes a minute or two…" : "⌘↵ to send"}
          </span>
          <button
            onClick={() => send.mutate()}
            disabled={!message.trim() || disabled || send.isPending}
            className="btn-primary"
          >
            {send.isPending ? "Revising…" : "Send"}
          </button>
        </div>
      </div>

      {send.error instanceof RequestFailed && (
        <p className="mt-2 text-sm text-red-700 dark:text-red-400">
          {send.error.message} {send.error.remedy}
        </p>
      )}
    </section>
  );
}
