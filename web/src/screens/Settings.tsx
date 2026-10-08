import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";
import type { BackendTest } from "../lib/api";

/** Which model does the work.
 *
 * Switching is a setting, not a code change: every agent talks to one
 * RunnerBackend, so this only decides which. A backend is checked before it is
 * saved, because the failure mode otherwise is choosing Codex, forgetting you
 * are not logged in, and finding out three minutes into a run.
 */
function Tracing() {
  const obs = useQuery({ queryKey: ["observability"], queryFn: api.observability });
  if (!obs.data) return null;
  const { langfuse, summary, evals } = obs.data;
  const state = langfuse.refused
    ? { text: `Refused — ${langfuse.refused}`, tone: "text-red-700 dark:text-red-400" }
    : !langfuse.enabled
      ? { text: "Off. Enable it in resume-tailor.toml once a self-hosted Langfuse is running.", tone: "text-stone-500" }
      : !langfuse.keys_set
        ? { text: `On for ${langfuse.host}, but the API key environment variables are not set.`, tone: "text-amber-700 dark:text-amber-400" }
        : { text: `Sending to ${langfuse.host}`, tone: "text-emerald-700 dark:text-emerald-400" };

  return (
    <div className="space-y-3 border-t border-stone-200 dark:border-stone-800 pt-6">
      <div>
        <h2 className="font-semibold">Tracing &amp; evals</h2>
        <p className="mt-1 text-xs text-stone-500">
          Every agent call is logged on this machine (<code className="font-mono">traces/</code>
          {obs.data.record_content ? ", prompts and outputs included" : ", metadata only"}). Langfuse
          is optional and must be self-hosted — a public address is refused because traces contain
          your whole knowledge base.
        </p>
      </div>
      <label className="flex cursor-pointer items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={obs.data.show_reasoning}
          onChange={async (event) => {
            await api.saveSettings({ observability: { show_reasoning: event.target.checked } });
            obs.refetch();
          }}
          className="mt-1"
        />
        <span>
          Show model reasoning in the live view
          <span className="block text-xs text-stone-500">
            Asks the model to expose its reasoning (Claude thinking tokens, Codex reasoning
            summaries). Costs extra tokens and time on every call, and not every model produces
            any — so it is off unless you want it.
          </span>
        </span>
      </label>
      <p className={`text-sm ${state.tone}`}>Langfuse: {state.text}</p>

      {summary.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="text-left text-stone-500">
              <tr>
                {["agent", "prompt", "backend", "calls", "errors", "avg s", "avg out"].map((h) => (
                  <th key={h} className="px-3 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {summary.map((r) => (
                <tr key={`${r.agent}${r.prompt_version}${r.backend}`} className="border-t border-stone-100 dark:border-stone-800">
                  <td className="px-3 py-1.5">{r.agent}</td>
                  <td className="px-3 py-1.5 font-mono text-stone-500">{r.prompt_version}</td>
                  <td className="px-3 py-1.5">{r.backend}</td>
                  <td className="px-3 py-1.5">{r.calls}</td>
                  <td className="px-3 py-1.5">{r.errors}</td>
                  <td className="px-3 py-1.5">{r.mean_seconds}</td>
                  <td className="px-3 py-1.5">{r.mean_output_tokens}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <h3 className="text-sm font-medium">Eval results</h3>
        {evals.length === 0 ? (
          <p className="mt-1 text-xs text-stone-500">
            None yet. <code className="font-mono">rt eval build &lt;run-id&gt;</code> then{" "}
            <code className="font-mono">rt eval run --label my-change</code>.
          </p>
        ) : (
          <ul className="mt-1 space-y-1 text-xs">
            {evals.map((e) => (
              <li key={e.name} className="flex flex-wrap gap-x-3">
                <span className="font-medium">{e.label}</span>
                <span className="text-stone-500">{e.backend}</span>
                {Object.entries(e.mean).sort().map(([k, v]) => (
                  <span key={k} className="tabular-nums text-stone-600 dark:text-stone-400">{k} {v}</span>
                ))}
                {e.reviewed_cases === 0 && <span className="text-amber-700 dark:text-amber-400">unreviewed cases</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function Settings() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [backend, setBackend] = useState<string | null>(null);
  const [models, setModels] = useState<Record<string, string>>({});
  const [tests, setTests] = useState<Record<string, BackendTest | "checking">>({});
  const [compat, setCompat] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!settings.data) return;
    setBackend(settings.data.backend);
    setModels(settings.data.models);
    setCompat(
      Object.fromEntries(
        Object.entries(settings.data.openai_compat).map(([k, v]) => [k, String(v)]),
      ),
    );
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      api.saveSettings({
        backend: backend!,
        models,
        openai_compat: {
          ...compat,
          context_tokens: Number(compat.context_tokens),
        } as never,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
      queryClient.invalidateQueries({ queryKey: ["health"] });
    },
  });

  async function check(name: string) {
    setTests((current) => ({ ...current, [name]: "checking" }));
    try {
      const result = await api.testBackend(name, models[name] || undefined);
      setTests((current) => ({ ...current, [name]: result }));
    } catch (error) {
      setTests((current) => ({
        ...current,
        [name]: { ok: false, detail: String(error), login: null },
      }));
    }
  }

  if (!settings.data || backend === null) return <p className="text-sm text-stone-500">Loading…</p>;
  const data = settings.data;
  const dirty =
    backend !== data.backend ||
    JSON.stringify(models) !== JSON.stringify(data.models) ||
    JSON.stringify(compat) !==
      JSON.stringify(
        Object.fromEntries(Object.entries(data.openai_compat).map(([k, v]) => [k, String(v)])),
      );
  const failure = save.error instanceof RequestFailed ? save.error : null;

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-stone-500">
          Choose which model runs the five agents, the revisions and the knowledge-base
          assistant. Saved to <code className="font-mono">{data.file ?? "resume-tailor.toml"}</code>{" "}
          on this machine only.
        </p>
      </div>

      {data.env_override && (
        <p className="rounded-lg border border-amber-300 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/30 p-3 text-sm text-amber-900 dark:text-amber-300">
          The server was started with <code className="font-mono">RUNNER_BACKEND</code> set, which
          overrides this screen — it is currently using{" "}
          <strong>{data.effective_backend}</strong>. Restart without it for your choice to apply.
        </p>
      )}

      <div className="space-y-3">
        {data.backends.map((info) => {
          const selected = backend === info.name;
          const test = tests[info.name];
          return (
            <div
              key={info.name}
              className={`card p-4 ${selected ? "ring-2 ring-stone-900 dark:ring-stone-100" : ""}`}
            >
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="radio"
                  name="backend"
                  checked={selected}
                  onChange={() => setBackend(info.name)}
                  className="mt-1"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline gap-2">
                    <span className="font-medium">{info.label}</span>
                    <code className="text-[11px] text-stone-400">{info.name}</code>
                    {data.backend === info.name && (
                      <span className="text-[11px] text-emerald-700 dark:text-emerald-400">
                        in use
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block text-xs text-stone-500">{info.blurb}</span>
                </span>
              </label>

              {selected && (
                <div className="mt-3 space-y-3 pl-7">
                  {info.name !== "openai_compat" ? (
                    <div>
                      <label className="block text-xs font-medium text-stone-500">
                        Model{" "}
                        <span className="font-normal">— empty uses that tool&apos;s own default</span>
                      </label>
                      <input
                        list={`models-${info.name}`}
                        value={models[info.name] ?? ""}
                        onChange={(event) =>
                          setModels({ ...models, [info.name]: event.target.value })
                        }
                        placeholder="default"
                        className="field mt-1 w-full max-w-xs"
                      />
                      <datalist id={`models-${info.name}`}>
                        {info.models.map((m) => (
                          <option key={m} value={m} />
                        ))}
                      </datalist>
                    </div>
                  ) : (
                    <div className="grid gap-2 sm:grid-cols-2">
                      {(
                        [
                          ["base_url", "Base URL"],
                          ["model", "Model"],
                          ["api_key_env", "API key env var"],
                          ["context_tokens", "Context window (tokens)"],
                        ] as const
                      ).map(([key, label]) => (
                        <div key={key}>
                          <label className="text-xs font-medium text-stone-500">{label}</label>
                          <input
                            value={compat[key] ?? ""}
                            onChange={(event) =>
                              setCompat({ ...compat, [key]: event.target.value })
                            }
                            className="field mt-1 w-full"
                          />
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      onClick={() => check(info.name)}
                      disabled={test === "checking"}
                      className="btn-secondary text-xs"
                    >
                      {test === "checking" ? "Checking…" : "Test connection"}
                    </button>
                    {test && test !== "checking" && (
                      <span
                        className={`text-xs ${test.ok ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400"}`}
                      >
                        {test.ok ? "Ready" : "Not ready"}
                        {test.detail ? ` — ${test.detail}` : ""}
                        {!test.ok && test.login && (
                          <>
                            {" "}
                            Run <code className="font-mono">{test.login}</code> in a terminal.
                          </>
                        )}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={() => save.mutate()}
          disabled={!dirty || save.isPending}
          className="btn-primary"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
        {!dirty && save.isSuccess && (
          <span className="text-sm text-emerald-700 dark:text-emerald-400">
            Saved — new runs use it.
          </span>
        )}
        {failure && (
          <span className="text-sm text-red-700 dark:text-red-400">
            {failure.message}
            {failure.remedy ? ` ${failure.remedy}` : ""}
          </span>
        )}
      </div>
      <p className="text-xs text-stone-500">
        A run already in progress keeps the backend it started with; changes apply to the next
        run or message.
      </p>

      <Tracing />
    </div>
  );
}
