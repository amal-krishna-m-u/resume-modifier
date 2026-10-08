import { useEffect, useRef, useState } from "react";
import { Inline } from "../lib/inline";

/** What the agents are doing, as it happens.
 *
 * Each model call is a row: which agent, how long, how many tokens, and, when
 * expanded, what it was asked, what it is writing right now, any reasoning the
 * backend exposes, and the finished result. Reasoning is opt-in (Settings): it
 * costs extra tokens, and not every backend or model produces any.
 */

interface Call {
  id: string;
  agent: string;
  kind?: string | null;
  backend?: string;
  model?: string | null;
  promptVersion?: string;
  startedAt: number;
  input?: string;
  inputChars?: number;
  live: string;
  thinking: string;
  reasoning: string[];
  status: "running" | "done" | "error";
  seconds?: number;
  usage?: { input_tokens?: number; output_tokens?: number; cache_read_tokens?: number };
  repairs?: number;
  error?: string | null;
  output?: unknown;
}

type Frame = Record<string, any>;

function reduce(calls: Call[], event: string, data: Frame): Call[] {
  if (event === "call_start") {
    if (calls.some((c) => c.id === data.id)) return calls;
    return [
      ...calls,
      {
        id: data.id,
        agent: data.agent,
        kind: data.kind,
        backend: data.backend,
        model: data.model,
        promptVersion: data.prompt_version,
        startedAt: data.at ? Date.parse(data.at) : Date.now(),
        input: data.input,
        inputChars: data.input_chars,
        live: "",
        thinking: "",
        reasoning: [],
        status: "running",
      },
    ];
  }
  return calls.map((c) => {
    if (c.id !== data.id) return c;
    switch (event) {
      case "output":
        return { ...c, live: data.text };
      case "thinking":
        return { ...c, thinking: data.text };
      case "reasoning":
        return { ...c, reasoning: [...c.reasoning, data.text], thinking: "" };
      case "call_end":
        return {
          ...c,
          status: data.error ? "error" : "done",
          seconds: data.seconds,
          usage: data.usage,
          repairs: data.repairs,
          error: data.error,
          output: data.output,
          thinking: "",
        };
      default:
        return c;
    }
  });
}

const AGENT_TONE: Record<string, string> = {
  analyst: "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300",
  selector: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  recall: "bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-300",
  writer: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  validator: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  curator: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
};

export function LiveTrace({
  traceKey,
  defaultOpen = false,
  onlyWhileActive = false,
}: {
  traceKey: string;
  defaultOpen?: boolean;
  /** Hide the panel until something has happened. */
  onlyWhileActive?: boolean;
}) {
  const [calls, setCalls] = useState<Call[]>([]);
  const [open, setOpen] = useState(defaultOpen);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [now, setNow] = useState(Date.now());
  const sawLive = useRef(false);

  useEffect(() => {
    setCalls([]);
    sawLive.current = false;
    let cancelled = false;

    // Past calls come from the log; the stream replays only what this server
    // process has seen. Once the stream speaks it replaces the log's copy.
    fetch(`/api/trace/${encodeURIComponent(traceKey)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (cancelled || !body || sawLive.current) return;
        setCalls(
          body.calls.map((c: Frame, index: number): Call => ({
            id: `log-${index}`,
            agent: c.agent,
            kind: c.kind,
            backend: c.backend,
            model: c.model,
            promptVersion: c.prompt_version,
            startedAt: Date.parse(c.at),
            input: c.input ?? undefined,
            live: "",
            thinking: "",
            reasoning: c.reasoning ?? [],
            status: c.error ? "error" : "done",
            seconds: c.seconds,
            usage: c.usage,
            repairs: c.repairs,
            error: c.error,
            output: c.output,
          })),
        );
      })
      .catch(() => undefined);

    const source = new EventSource(`/api/trace/${encodeURIComponent(traceKey)}/events`);
    for (const name of ["call_start", "output", "thinking", "reasoning", "call_end"]) {
      source.addEventListener(name, (message) => {
        const data = JSON.parse((message as MessageEvent).data) as Frame;
        setCalls((current) => {
          if (!sawLive.current) {
            sawLive.current = true;
            current = [];
          }
          return reduce(current, name, data);
        });
      });
    }
    return () => {
      cancelled = true;
      source.close();
    };
  }, [traceKey]);

  const running = calls.filter((c) => c.status === "running");
  useEffect(() => {
    if (running.length === 0) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running.length]);

  // Open itself when something starts, so a run shows its activity without a click.
  useEffect(() => {
    if (running.length > 0) setOpen(true);
  }, [running.length]);

  if (calls.length === 0 && onlyWhileActive) return null;
  if (calls.length === 0)
    return <p className="text-xs text-stone-400">No agent activity recorded for this yet.</p>;

  const tokens = calls.reduce(
    (sum, c) => sum + (c.usage?.input_tokens ?? 0) + (c.usage?.cache_read_tokens ?? 0),
    0,
  );
  const out = calls.reduce((sum, c) => sum + (c.usage?.output_tokens ?? 0), 0);

  return (
    <div className="card">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm"
      >
        <span
          className={`size-2 rounded-full ${running.length ? "animate-pulse bg-sky-500" : "bg-stone-400"}`}
        />
        <span className="font-medium">Agent activity</span>
        <span className="text-xs tabular-nums text-stone-500">
          {calls.length} call{calls.length === 1 ? "" : "s"}
          {tokens > 0 && ` · ${tokens.toLocaleString()} prompt · ${out.toLocaleString()} output tokens`}
          {running.length > 0 && ` · ${running.map((c) => c.agent).join(", ")} working`}
        </span>
        <span className="ml-auto text-xs text-stone-400">{open ? "hide" : "show"}</span>
      </button>

      {open && (
        <ul className="divide-y divide-stone-200 border-t border-stone-200 dark:divide-stone-800 dark:border-stone-800">
          {calls.map((call) => (
            <CallRow
              key={call.id}
              call={call}
              now={now}
              open={expanded[call.id] ?? call.status === "running"}
              toggle={() =>
                setExpanded({ ...expanded, [call.id]: !(expanded[call.id] ?? call.status === "running") })
              }
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function CallRow({
  call,
  now,
  open,
  toggle,
}: {
  call: Call;
  now: number;
  open: boolean;
  toggle: () => void;
}) {
  const elapsed =
    call.status === "running"
      ? Math.max(0, Math.round((now - call.startedAt) / 1000))
      : Math.round(call.seconds ?? 0);
  const result =
    call.output === undefined || call.output === null
      ? ""
      : typeof call.output === "string"
        ? call.output
        : JSON.stringify(call.output, null, 2);
  const thoughts = [...call.reasoning, ...(call.thinking ? [call.thinking] : [])];

  return (
    <li className="px-4 py-2">
      <button onClick={toggle} className="flex w-full flex-wrap items-center gap-2 text-left text-xs">
        <span
          className={`rounded px-1.5 py-0.5 font-medium ${AGENT_TONE[call.agent] ?? "bg-stone-100 dark:bg-stone-800"}`}
        >
          {call.agent}
        </span>
        {call.kind && call.kind !== "tailor" && <span className="text-stone-400">{call.kind}</span>}
        {call.status === "running" && (
          <span className="flex items-center gap-1 text-sky-700 dark:text-sky-400">
            <span className="size-1.5 animate-pulse rounded-full bg-sky-500" />
            working
          </span>
        )}
        {call.status === "done" && <span className="text-emerald-700 dark:text-emerald-400">done</span>}
        {call.status === "error" && <span className="text-red-700 dark:text-red-400">failed</span>}
        <span className="tabular-nums text-stone-500">{elapsed}s</span>
        {call.usage?.output_tokens ? (
          <span className="tabular-nums text-stone-500">
            {call.usage.output_tokens.toLocaleString()} out
          </span>
        ) : null}
        {call.repairs ? <span className="text-amber-700 dark:text-amber-400">repaired ×{call.repairs}</span> : null}
        <span className="ml-auto text-stone-400">
          {call.backend}
          {call.model ? ` · ${call.model}` : ""}
          {call.promptVersion ? ` · prompt ${call.promptVersion}` : ""}
        </span>
      </button>

      {open && (
        <div className="mt-2 space-y-2 text-xs">
          {call.error && (
            <p className="rounded bg-red-50 p-2 text-red-800 dark:bg-red-950/40 dark:text-red-300">
              {call.error}
            </p>
          )}

          {thoughts.length > 0 ? (
            <Section title="Reasoning">
              {thoughts.map((t, i) => (
                <p key={i} className="whitespace-pre-wrap leading-relaxed text-stone-700 dark:text-stone-300">
                  <Inline text={t} />
                </p>
              ))}
            </Section>
          ) : (
            call.status === "running" && (
              <p className="text-stone-400">
                No reasoning is being shown. Turn on “Show model reasoning” in Settings; not every
                model produces any.
              </p>
            )
          )}

          {call.status === "running" && call.live && (
            <Section title="Writing now">
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-snug">
                {call.live}
              </pre>
            </Section>
          )}

          {result && (
            <Section title="Result">
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-snug">
                {result}
              </pre>
            </Section>
          )}

          {call.input && (
            <details>
              <summary className="cursor-pointer text-stone-500">
                What it was asked
                {call.inputChars ? ` (${call.inputChars.toLocaleString()} characters; the knowledge base is not repeated here)` : ""}
              </summary>
              <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-snug text-stone-600 dark:text-stone-400">
                {call.input}
              </pre>
            </details>
          )}
        </div>
      )}
    </li>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wide text-stone-400">{title}</div>
      <div className="rounded bg-stone-50 p-2 dark:bg-stone-900/60">{children}</div>
    </div>
  );
}
