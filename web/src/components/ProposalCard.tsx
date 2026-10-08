import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";
import { GUIDES, bodyWords, thinness } from "../lib/guidance";
import type { IndexRow, Proposal } from "../lib/types";

/** One change the assistant proposes, shown as exactly what would be written.
 *
 * Nothing here is saved until Accept. The card exists so that review is quick
 * and mistakes are visible: the validation result is computed *before* you look
 * (an invalid proposal cannot be accepted), an update shows only the part that
 * changes, and a new entry shows everything it would contain. */
export function ProposalCard({
  proposal,
  scope,
  entries,
  acceptedIds,
  blockedReason,
  onOpenEntry,
}: {
  proposal: Proposal;
  scope: string;
  entries: IndexRow[];
  /** Entries accepted earlier in this conversation, for dependency checks. */
  acceptedIds: Set<string>;
  /** Why accepting is held up right now, e.g. unsaved edits in the editor. */
  blockedReason?: string | null;
  onOpenEntry?: (type: string, id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [collapsed, setCollapsed] = useState(
    proposal.status === "rejected" || proposal.status === "superseded",
  );

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["kb"] });
    queryClient.invalidateQueries({ queryKey: ["kbchat", scope] });
  };

  const accept = useMutation({
    mutationFn: () => api.kbChatAccept(scope, proposal.id),
    onSuccess: refresh,
    onError: refresh,
  });
  const reject = useMutation({
    mutationFn: () => api.kbChatReject(scope, proposal.id),
    onSuccess: refresh,
  });

  const fields = proposal.fields as Record<string, any>;
  const guide = GUIDES[proposal.type];
  const parent = typeof fields.parent === "string" ? entries.find((e) => e.id === fields.parent) : null;

  const waiting = proposal.depends_on.filter((id) => !acceptedIds.has(id));
  const invalid = proposal.errors.length > 0;
  const holdReason = blockedReason
    ? blockedReason
    : invalid
      ? "Fix the problems below first — ask the assistant to correct them."
      : waiting.length > 0
        ? `Accept ${waiting.join(", ")} first — this sits under it.`
        : null;

  const failure = accept.error instanceof RequestFailed ? accept.error : null;
  const done = proposal.status !== "pending";

  if (done && collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="flex w-full items-center gap-2 rounded-lg border border-stone-200 dark:border-stone-800 px-3 py-2 text-left text-xs text-stone-500"
      >
        <Status status={proposal.status} />
        <span className="truncate">
          {proposal.op} {guide?.label.toLowerCase() ?? proposal.type} · {proposal.entry_id}
        </span>
        <span className="ml-auto">show</span>
      </button>
    );
  }

  return (
    <div
      className={`rounded-lg border p-4 space-y-3 ${
        proposal.status === "accepted"
          ? "border-emerald-300 dark:border-emerald-900 bg-emerald-50/40 dark:bg-emerald-950/20"
          : "border-stone-300 dark:border-stone-700"
      }`}
    >
      <div className="flex items-start gap-2">
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
            proposal.op === "create"
              ? "bg-sky-100 dark:bg-sky-950 text-sky-800 dark:text-sky-300"
              : "bg-violet-100 dark:bg-violet-950 text-violet-800 dark:text-violet-300"
          }`}
        >
          {proposal.op === "create" ? "New" : "Update"}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium leading-snug">
            {proposal.title ?? proposal.entry_id}
          </div>
          <div className="text-[11px] text-stone-400">
            {guide?.label ?? proposal.type} · <code className="font-mono">{proposal.entry_id}</code>
          </div>
        </div>
        {done && <Status status={proposal.status} />}
        {done && proposal.status !== "accepted" && (
          <button onClick={() => setCollapsed(true)} className="text-[11px] text-stone-400">
            hide
          </button>
        )}
      </div>

      {proposal.reason && (
        <p className="text-xs text-stone-600 dark:text-stone-400 leading-relaxed">
          {proposal.reason}
        </p>
      )}

      {/* ----- what would be written ------------------------------------- */}
      {proposal.op === "create" ? (
        <dl className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
          {parent && (
            <Row label="Sits under">
              {parent.title}
              {parent.org ? <span className="text-stone-400"> · {parent.org}</span> : null}
            </Row>
          )}
          {!parent && typeof fields.parent === "string" && (
            <Row label="Sits under">
              <code className="font-mono">{fields.parent}</code>
            </Row>
          )}
          {(fields.org || fields.dates) && (
            <Row label="Where / when">
              {[fields.org, fields.dates?.start && `${fields.dates.start} – ${fields.dates.end ?? ""}`]
                .filter(Boolean)
                .join(" · ")}
            </Row>
          )}
          <Row label="Depth">
            <strong className="font-medium">{String(fields.depth ?? "working")}</strong>
            <span className="text-stone-400"> — how strongly it may be framed</span>
          </Row>
          <Row label="Visibility">{String(fields.visibility ?? "public")}</Row>
          {Array.isArray(fields.tags) && fields.tags.length > 0 && (
            <Row label="Tags">
              <Chips items={fields.tags as string[]} />
            </Row>
          )}
          {Array.isArray(fields.metrics) && fields.metrics.length > 0 && (
            <Row label="Metrics">
              {(fields.metrics as { value: string; what: string }[]).map((m, i) => (
                <div key={i}>
                  <strong className="font-medium">{m.value}</strong>{" "}
                  <span className="text-stone-500">{m.what}</span>
                </div>
              ))}
            </Row>
          )}
        </dl>
      ) : (
        <ul className="space-y-1.5 text-xs">
          {proposal.fields_changed.map((change) => (
            <li key={change.field} className="flex gap-2">
              <span className="w-16 shrink-0 text-stone-400">{change.field}</span>
              <FieldChange before={change.before} after={change.after} />
            </li>
          ))}
        </ul>
      )}

      {/* ----- the body ---------------------------------------------------- */}
      {proposal.op === "update" && proposal.body_added ? (
        <Block tone="add" label="Adds to the body">
          {proposal.body_added}
        </Block>
      ) : proposal.op === "update" && proposal.body_before !== proposal.body_after ? (
        <div className="space-y-2">
          <Block tone="remove" label="Body before">
            {proposal.body_before ?? ""}
          </Block>
          <Block tone="add" label="Body after">
            {proposal.body_after}
          </Block>
        </div>
      ) : proposal.op === "create" ? (
        <div>
          <Block tone="neutral" label="Body">
            {proposal.body_after || "(empty)"}
          </Block>
          <BodyDepth body={proposal.body_after} type={proposal.type} />
        </div>
      ) : null}

      {/* ----- validation, before you look -------------------------------- */}
      {proposal.errors.length > 0 && (
        <ul className="space-y-1 rounded-md bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 p-2.5 text-xs text-red-800 dark:text-red-300">
          {proposal.errors.map((issue, i) => (
            <li key={i}>
              {issue.field && <code className="font-mono">{issue.field}</code>} {issue.message}
            </li>
          ))}
        </ul>
      )}
      {proposal.warnings.length > 0 && (
        <ul className="space-y-1 rounded-md bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900 p-2.5 text-xs text-amber-900 dark:text-amber-300">
          {proposal.warnings.map((issue, i) => (
            <li key={i}>{issue.message}</li>
          ))}
        </ul>
      )}

      {failure && (
        <div className="rounded-md bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 p-2.5 text-xs text-red-800 dark:text-red-300">
          <div className="font-medium">{failure.message}</div>
          {failure.remedy && <div className="mt-0.5">{failure.remedy}</div>}
        </div>
      )}

      {/* ----- actions ------------------------------------------------------ */}
      {proposal.status === "pending" && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <button
              onClick={() => accept.mutate()}
              disabled={accept.isPending || holdReason !== null}
              className="btn-primary"
            >
              {accept.isPending ? "Saving…" : proposal.op === "create" ? "Add to knowledge base" : "Apply this change"}
            </button>
            <button
              onClick={() => reject.mutate()}
              disabled={reject.isPending}
              className="btn-ghost"
            >
              Reject
            </button>
          </div>
          {holdReason ? (
            <p className="text-[11px] text-amber-700 dark:text-amber-400">{holdReason}</p>
          ) : (
            <p className="text-[11px] text-stone-400">
              Nothing is saved until you accept. It lands as a commit in your local{" "}
              <code className="font-mono">kb/</code> repository, so it can be reverted.
            </p>
          )}
        </div>
      )}

      {proposal.status === "accepted" && (
        <div className="flex items-center gap-3 text-xs text-emerald-700 dark:text-emerald-400">
          <span>
            Saved{proposal.commit ? ` · commit ${proposal.commit.slice(0, 7)}` : ""}
          </span>
          {onOpenEntry && (
            <button
              onClick={() => onOpenEntry(proposal.type, proposal.entry_id)}
              className="underline"
            >
              View entry →
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Status({ status }: { status: Proposal["status"] }) {
  const tone: Record<string, string> = {
    pending: "text-stone-500",
    accepted: "text-emerald-600 dark:text-emerald-400",
    rejected: "text-stone-400",
    superseded: "text-stone-400",
  };
  const label: Record<string, string> = {
    pending: "pending",
    accepted: "accepted",
    rejected: "rejected",
    superseded: "replaced by a newer one",
  };
  return <span className={`text-[11px] ${tone[status]}`}>{label[status]}</span>;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-stone-400">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  );
}

function Chips({ items }: { items: string[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((item) => (
        <span key={item} className="rounded bg-stone-100 dark:bg-stone-800 px-1.5 py-0.5">
          {item}
        </span>
      ))}
    </span>
  );
}

/** A field's change, shown as the change and not as two whole values. */
function FieldChange({ before, after }: { before: unknown; after: unknown }) {
  if (Array.isArray(before) || Array.isArray(after)) {
    const b = Array.isArray(before) ? before : [];
    const a = Array.isArray(after) ? after : [];
    const key = (x: unknown) => JSON.stringify(x);
    const added = a.filter((x) => !b.some((y) => key(y) === key(x)));
    const removed = b.filter((x) => !a.some((y) => key(y) === key(x)));
    const show = (x: unknown) =>
      typeof x === "object" && x !== null
        ? `${(x as any).value ?? ""} ${(x as any).what ?? ""}`.trim()
        : String(x);
    return (
      <span className="flex flex-wrap gap-1">
        {added.map((x, i) => (
          <span key={`a${i}`} className="rounded bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300 px-1.5 py-0.5">
            + {show(x)}
          </span>
        ))}
        {removed.map((x, i) => (
          <span key={`r${i}`} className="rounded bg-red-100 dark:bg-red-950 text-red-800 dark:text-red-300 px-1.5 py-0.5">
            − {show(x)}
          </span>
        ))}
      </span>
    );
  }
  const text = (x: unknown) =>
    typeof x === "object" && x !== null ? JSON.stringify(x) : String(x ?? "—");
  return (
    <span>
      <span className="text-stone-400 line-through">{text(before)}</span>
      {" → "}
      <strong className="font-medium">{text(after)}</strong>
    </span>
  );
}

function Block({
  tone,
  label,
  children,
}: {
  tone: "add" | "remove" | "neutral";
  label: string;
  children: string;
}) {
  const tones = {
    add: "border-emerald-300 dark:border-emerald-900 bg-emerald-50/60 dark:bg-emerald-950/20",
    remove: "border-red-200 dark:border-red-900 bg-red-50/50 dark:bg-red-950/20 opacity-80",
    neutral: "border-stone-200 dark:border-stone-800 bg-stone-50 dark:bg-stone-900/50",
  };
  return (
    <div className={`rounded-md border px-3 py-2 ${tones[tone]}`}>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-stone-400">
        {label}
      </div>
      <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed">{children}</p>
    </div>
  );
}

/** Whether a new entry's body is likely to carry a claim. The same bar the list
 * uses — a one-line body is a resume bullet, which the writer produces rather
 * than consumes. */
function BodyDepth({ body, type }: { body: string; type: string }) {
  const state = thinness(body, type);
  if (state === "ok") return null;
  return (
    <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">
      {bodyWords(body)} words — thin. Answer the assistant's questions and it will propose a
      fuller version; you can also expand it in the form after accepting.
    </p>
  );
}
