import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, watchKb } from "./lib/api";
import { NewRun } from "./screens/NewRun";
import { RunScreen } from "./screens/RunScreen";
import { KbBrowser } from "./screens/KbBrowser";
import { ApplicationDetail, Tracker } from "./screens/Tracker";
import { HealthBadge } from "./components/HealthBadge";

type View =
  | { name: "new" }
  | { name: "run"; id: string }
  | { name: "kb" }
  | { name: "tracker" }
  | { name: "application"; id: string };

/** Hash routing. No router dependency for three screens on one machine. */
function useRoute(): [View, (view: View) => void] {
  const parse = (): View => {
    const hash = window.location.hash.replace(/^#\/?/, "");
    if (hash.startsWith("run/")) return { name: "run", id: hash.slice(4) };
    if (hash.startsWith("application/")) return { name: "application", id: hash.slice(12) };
    if (hash === "kb") return { name: "kb" };
    if (hash === "tracker") return { name: "tracker" };
    return { name: "new" };
  };

  const [view, setView] = useState<View>(parse);

  useEffect(() => {
    const onChange = () => setView(parse());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const navigate = (next: View) => {
    window.location.hash =
      next.name === "run"
        ? `/run/${next.id}`
        : next.name === "application"
          ? `/application/${next.id}`
          : next.name === "kb"
            ? "/kb"
            : next.name === "tracker"
              ? "/tracker"
              : "/";
  };

  return [view, navigate];
}

export function App() {
  const [view, navigate] = useRoute();
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    // Cheap, and it is how a running job stays findable from any screen.
    refetchInterval: 5000,
  });

  const active = (runs.data?.runs ?? []).filter((run) => run.running);

  // Editing in the browser, in vim, and an agent proposal are three paths to
  // the same bytes (spec-01 P1), so the UI has to learn about the other two.
  useEffect(
    () =>
      watchKb(() => {
        queryClient.invalidateQueries({ queryKey: ["kb"] });
      }),
    [queryClient],
  );

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 dark:border-stone-800 sticky top-0 bg-stone-50/90 dark:bg-stone-950/90 backdrop-blur z-10">
        <div className="mx-auto max-w-7xl px-4 h-14 flex items-center gap-6">
          <button
            onClick={() => navigate({ name: "new" })}
            className="font-semibold tracking-tight hover:opacity-70"
          >
            resume-tailor
          </button>
          <nav className="flex gap-1 text-sm">
            <Tab active={view.name === "new"} onClick={() => navigate({ name: "new" })}>
              New run
            </Tab>
            <Tab
              active={view.name === "tracker" || view.name === "application"}
              onClick={() => navigate({ name: "tracker" })}
            >
              Applications
            </Tab>
            <Tab active={view.name === "kb"} onClick={() => navigate({ name: "kb" })}>
              Knowledge base
            </Tab>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {/* A running job stays reachable from every screen. Without this,
                navigating away from one meant losing track of it entirely. */}
            {active.map((run) => (
              <button
                key={run.id}
                onClick={() => navigate({ name: "run", id: run.id })}
                className="flex items-center gap-2 rounded border border-sky-300 dark:border-sky-800 bg-sky-50 dark:bg-sky-950/40 px-2.5 py-1 text-xs"
                title={run.id}
              >
                <span className="size-1.5 rounded-full bg-sky-500 animate-pulse" />
                <span className="max-w-40 truncate">
                  {run.stages.includes("validation")
                    ? "finishing"
                    : run.stages.includes("draft")
                      ? "validating"
                      : run.stages.includes("merged")
                        ? "writing"
                        : run.stages.includes("requirements")
                          ? "selecting"
                          : "analysing"}
                </span>
              </button>
            ))}

            {runs.data && runs.data.runs.length > 0 && (
              <select
                className="text-sm bg-transparent border border-stone-300 dark:border-stone-700 rounded px-2 py-1 max-w-64"
                value={view.name === "run" ? view.id : ""}
                onChange={(event) =>
                  event.target.value && navigate({ name: "run", id: event.target.value })
                }
              >
                <option value="">Runs…</option>
                {runs.data.runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.running ? "● " : run.complete ? "" : "· "}
                    {run.id}
                  </option>
                ))}
              </select>
            )}
            <HealthBadge />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8">
        {view.name === "new" && <NewRun onStarted={(id) => navigate({ name: "run", id })} />}
        {view.name === "run" && <RunScreen runId={view.id} />}
        {view.name === "kb" && <KbBrowser />}
        {view.name === "tracker" && (
          <Tracker onOpen={(id) => navigate({ name: "application", id })} />
        )}
        {view.name === "application" && (
          <ApplicationDetail id={view.id} onBack={() => navigate({ name: "tracker" })} />
        )}
      </main>
    </div>
  );
}

function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded transition-colors ${
        active
          ? "bg-stone-200 dark:bg-stone-800 font-medium"
          : "hover:bg-stone-100 dark:hover:bg-stone-900 text-stone-600 dark:text-stone-400"
      }`}
    >
      {children}
    </button>
  );
}
