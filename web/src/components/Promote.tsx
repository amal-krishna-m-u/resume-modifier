import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";

/** Promotion is explicit (spec-07 §1).
 *
 * Exporting a PDF does not create a record — you often export just to look at
 * something. This is the moment the system can know the content became
 * permanent, which is why it is a deliberate action and not a side effect. */
export function Promote({ runId, onDone }: { runId: string; onDone: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    company: "",
    role: "",
    job_id: "",
    source: "direct",
    contact_set_sent: "",
  });

  const promote = useMutation({
    mutationFn: () =>
      api.promote(runId, {
        company: form.company.trim(),
        role: form.role.trim(),
        job_id: form.job_id.trim() || undefined,
        source: form.source,
        contact_set_sent: form.contact_set_sent || undefined,
      }),
    onSuccess: (result) => onDone(result.id),
  });

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded border border-stone-300 dark:border-stone-700 px-3 py-1.5 text-sm hover:bg-stone-100 dark:hover:bg-stone-900"
      >
        I applied
      </button>
    );
  }

  const field = (key: keyof typeof form, label: string, placeholder = "") => (
    <label className="block">
      <span className="text-xs font-medium text-stone-500">{label}</span>
      <input
        value={form[key]}
        placeholder={placeholder}
        onChange={(event) => setForm({ ...form, [key]: event.target.value })}
        className="mt-1 w-full rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 px-2 py-1.5 text-sm"
      />
    </label>
  );

  return (
    <div className="rounded border border-stone-300 dark:border-stone-700 p-4 w-80 space-y-3">
      <p className="text-xs text-stone-500 leading-relaxed">
        This freezes what you sent. The resumes and the content snapshot become read-only and
        hashed; status, stages and referrals stay editable.
      </p>
      {field("company", "Company")}
      {field("role", "Role")}
      {field("job_id", "Job ID", "optional, but it is what a recruiter quotes back")}
      {field("contact_set_sent", "Contact set sent", "which one actually went out")}

      <div className="flex gap-2">
        <button
          onClick={() => promote.mutate()}
          disabled={!form.company.trim() || !form.role.trim() || promote.isPending}
          className="flex-1 rounded bg-stone-900 dark:bg-stone-100 text-stone-50 dark:text-stone-900 px-3 py-1.5 text-sm font-medium disabled:opacity-40"
        >
          {promote.isPending ? "Freezing…" : "Record it"}
        </button>
        <button
          onClick={() => setOpen(false)}
          className="rounded border border-stone-300 dark:border-stone-700 px-3 py-1.5 text-sm"
        >
          Cancel
        </button>
      </div>

      {promote.error instanceof RequestFailed && (
        <p className="text-xs text-red-700 dark:text-red-400">
          {promote.error.message} {promote.error.remedy}
        </p>
      )}
    </div>
  );
}
