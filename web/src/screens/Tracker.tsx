import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";
import type { ApplicationRow, Divergence } from "../lib/types";

const STATUSES = [
  "draft", "applied", "screening", "interview", "offer",
  "rejected", "withdrawn", "ghosted",
] as const;

const LIVE = new Set(["applied", "screening", "interview", "offer"]);

/** Screen 6.6 — the tracker (R19). */
export function Tracker({ onOpen }: { onOpen: (id: string) => void }) {
  const [liveOnly, setLiveOnly] = useState(false);
  const [status, setStatus] = useState<string>("");

  const applications = useQuery({
    queryKey: ["applications", { liveOnly, status }],
    queryFn: () => api.applications({ liveOnly, status: status || undefined }),
  });

  const rows = applications.data?.applications ?? [];
  const pipeline = applications.data?.pipeline ?? {};
  const live = Object.entries(pipeline)
    .filter(([name]) => LIVE.has(name))
    .reduce((sum, [, count]) => sum + count, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between gap-4 flex-wrap">
        <h1 className="text-xl font-semibold tracking-tight">Applications</h1>
        <div className="flex items-center gap-3 text-sm">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={liveOnly}
              onChange={(event) => setLiveOnly(event.target.checked)}
            />
            Live only
          </label>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="rounded border border-stone-300 dark:border-stone-700 bg-transparent px-2 py-1"
          >
            <option value="">All statuses</option>
            {STATUSES.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* The count that matters when deciding whether to keep applying is how
          many are live, not how many were sent. */}
      <div className="flex flex-wrap gap-2 text-sm">
        <Count label="live" value={live} tone="emerald" />
        {STATUSES.filter((name) => pipeline[name]).map((name) => (
          <Count key={name} label={name} value={pipeline[name]!} />
        ))}
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-stone-500">
          Nothing recorded yet. After you send a resume, promote its run — that is the moment
          the content freezes, so a callback three months from now can be prepared against
          what you actually sent.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-stone-500 border-b border-stone-200 dark:border-stone-800">
              <th className="py-2 font-medium">Applied</th>
              <th className="py-2 font-medium">Company</th>
              <th className="py-2 font-medium">Role</th>
              <th className="py-2 font-medium">Status</th>
              <th className="py-2 font-medium">Referral</th>
              <th className="py-2 font-medium">Sent as</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Row key={row.id} row={row} onOpen={() => onOpen(row.id)} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Row({ row, onOpen }: { row: ApplicationRow; onOpen: () => void }) {
  const queryClient = useQueryClient();
  const patch = useMutation({
    mutationFn: (status: string) => api.patchApplication(row.id, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["applications"] }),
  });

  return (
    <tr className="border-b border-stone-100 dark:border-stone-900 hover:bg-stone-50 dark:hover:bg-stone-900/50">
      <td className="py-2 tabular-nums text-stone-500">{row.applied_on}</td>
      <td className="py-2">
        <button onClick={onOpen} className="hover:underline text-left">
          {row.company}
        </button>
      </td>
      <td className="py-2">{row.role}</td>
      <td className="py-2">
        <select
          value={row.status}
          onChange={(event) => patch.mutate(event.target.value)}
          className="bg-transparent border border-stone-300 dark:border-stone-700 rounded px-1.5 py-0.5 text-xs"
        >
          {STATUSES.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </td>
      <td className="py-2 text-stone-500">
        {row.referral_received ? (row.referrer ?? "yes") : "—"}
      </td>
      <td className="py-2 text-stone-500">{row.contact_set_sent ?? "—"}</td>
    </tr>
  );
}

function Count({
  label,
  value,
  tone = "stone",
}: {
  label: string;
  value: number;
  tone?: "stone" | "emerald";
}) {
  return (
    <span
      className={`rounded px-2 py-1 ${
        tone === "emerald"
          ? "bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300 font-medium"
          : "bg-stone-100 dark:bg-stone-900 text-stone-600 dark:text-stone-400"
      }`}
    >
      {value} {label}
    </span>
  );
}

/** Screen 6.7 — one application, with the snapshot beside the current KB (R20). */
export function ApplicationDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const detail = useQuery({ queryKey: ["application", id], queryFn: () => api.application(id) });
  const snapshot = useQuery({
    queryKey: ["application", id, "snapshot"],
    queryFn: () => api.applicationSnapshot(id),
  });
  const integrity = useQuery({
    queryKey: ["application", id, "verify"],
    queryFn: () => api.verifyApplication(id),
  });

  const application = detail.data?.application;
  const divergence = snapshot.data?.divergence ?? [];

  return (
    <div className="space-y-6">
      <button onClick={onBack} className="text-sm text-stone-500 hover:underline">
        ← All applications
      </button>

      {application && (
        <>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              {application.role} · {application.company}
            </h1>
            <p className="text-xs text-stone-500 mt-1">
              Applied {application.applied_on}
              {application.job_id && ` · ${application.job_id}`}
              {application.source && ` · via ${application.source}`}
              {application.contact_set_sent && ` · sent as ${application.contact_set_sent}`}
            </p>
          </div>

          {integrity.data && !integrity.data.intact && (
            <div className="rounded border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/30 p-3 text-sm">
              <strong>Archived files have changed since they were sent.</strong>
              <ul className="mt-1 text-xs">
                {integrity.data.problems.map((problem, index) => (
                  <li key={index}>
                    {problem.file}: {problem.issue}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {(detail.data?.files ?? [])
              .filter((name) => name.endsWith(".pdf") || name.endsWith(".tex"))
              .map((name) => (
                <span
                  key={name}
                  className="rounded border border-stone-300 dark:border-stone-700 px-2 py-1 text-xs font-mono"
                >
                  {name}
                </span>
              ))}
          </div>
        </>
      )}

      <section>
        <h2 className="text-sm font-semibold">
          Since you sent this
          {divergence.length > 0 && (
            <span className="ml-2 text-amber-700 dark:text-amber-400 font-normal">
              {divergence.length} fact{divergence.length === 1 ? "" : "s"} changed
            </span>
          )}
        </h2>
        <p className="mt-1 text-xs text-stone-500 leading-relaxed max-w-2xl">
          What matters walking into an interview is what the reader saw. Anything below has
          changed in your knowledge base since — so today's version would mislead you.
        </p>

        {divergence.length === 0 ? (
          <p className="mt-3 text-sm text-emerald-700 dark:text-emerald-400">
            Nothing has changed. Your knowledge base still says what this resume said.
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {divergence.map((change: Divergence) => (
              <li
                key={change.fact_id}
                className="rounded border border-amber-200 dark:border-amber-900 p-3"
              >
                <div className="flex items-center gap-2">
                  <code className="text-xs bg-stone-100 dark:bg-stone-900 px-1.5 py-0.5 rounded">
                    {change.fact_id}
                  </code>
                  <span className="text-xs text-amber-700 dark:text-amber-400">
                    {change.status}
                  </span>
                </div>
                {change.sent && (
                  <div className="mt-2 grid md:grid-cols-2 gap-3 text-xs">
                    <div>
                      <div className="font-medium text-stone-500 uppercase tracking-wide">
                        As sent
                      </div>
                      <p className="mt-1 leading-relaxed">{change.sent}</p>
                    </div>
                    {change.current && (
                      <div>
                        <div className="font-medium text-stone-500 uppercase tracking-wide">
                          Now
                        </div>
                        <p className="mt-1 leading-relaxed">{change.current}</p>
                      </div>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {snapshot.data?.snapshot && (
        <section>
          <h2 className="text-sm font-semibold">What you sent</h2>
          {snapshot.data.snapshot.summary && (
            <p className="mt-2 text-sm leading-relaxed">{snapshot.data.snapshot.summary}</p>
          )}
          <ul className="mt-3 space-y-2">
            {snapshot.data.snapshot.bullets.map((bullet, index) => (
              <li key={index} className="text-sm leading-relaxed">
                {bullet.lead && <strong>{bullet.lead}: </strong>}
                {bullet.text}
              </li>
            ))}
          </ul>
        </section>
      )}

      {detail.error instanceof RequestFailed && (
        <p className="text-sm text-red-700 dark:text-red-400">{detail.error.message}</p>
      )}
    </div>
  );
}
