import { useState } from "react";
import { GUIDES, bodyWords, thinness } from "../lib/guidance";

/** The body field, which asks questions instead of showing an empty box.
 *
 * This is the field that decides whether the whole system works. Selection can
 * only pick detail that exists, and a body written as one compressed sentence
 * is a resume bullet — which is what the writer is supposed to *produce*, not
 * consume. Every "matched, but not strongly" row in a gap report is this.
 */
export function BodyEditor({
  value,
  onChange,
  type,
}: {
  value: string;
  onChange: (body: string) => void;
  type: string;
}) {
  const guide = GUIDES[type];
  const [showPrompts, setShowPrompts] = useState(() => bodyWords(value) < 20);

  const words = bodyWords(value);
  const state = thinness(value, type);
  const target = guide?.target ?? 80;

  const tone =
    state === "ok"
      ? "text-emerald-700 dark:text-emerald-400"
      : state === "thin"
        ? "text-amber-700 dark:text-amber-400"
        : "text-stone-400";

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-stone-500">body</span>
        <div className="flex items-center gap-3 text-[11px]">
          <span className={tone}>
            {words} words
            {state === "thin" && ` · thin, aim for ~${target}`}
            {state === "empty" && " · nothing to select yet"}
            {state === "ok" && " · enough to carry a claim"}
          </span>
          {guide && (
            <button
              onClick={() => setShowPrompts(!showPrompts)}
              className="text-stone-500 hover:text-stone-900 dark:hover:text-stone-100 underline"
            >
              {showPrompts ? "hide prompts" : "what should I write?"}
            </button>
          )}
        </div>
      </div>

      {showPrompts && guide && (
        <div className="mt-1.5 rounded border border-stone-200 dark:border-stone-800 bg-stone-50 dark:bg-stone-900/50 p-3">
          <p className="text-xs text-stone-600 dark:text-stone-400">{guide.blurb}</p>
          <ul className="mt-2 space-y-1.5">
            {guide.prompts.map((prompt) => (
              <li key={prompt} className="flex items-start gap-2 text-xs">
                <button
                  onClick={() => {
                    const prefix = value.trim() ? `${value.trimEnd()}\n\n` : "";
                    onChange(`${prefix}${prompt}\n`);
                  }}
                  title="Add this as a heading to answer"
                  className="mt-0.5 text-stone-400 hover:text-stone-900 dark:hover:text-stone-100 shrink-0"
                >
                  +
                </button>
                <span className="text-stone-600 dark:text-stone-400">{prompt}</span>
              </li>
            ))}
          </ul>
          {guide.example && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-stone-500">
                What a good one looks like
              </summary>
              <p className="mt-1 text-xs text-stone-500 italic leading-relaxed">
                {guide.example}
              </p>
            </details>
          )}
          <p className="mt-2 text-[11px] text-stone-400 leading-relaxed">
            Write more here than any resume would use. The writer compresses per posting —
            it cannot expand what you did not record.
          </p>
        </div>
      )}

      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={14}
        placeholder={
          guide ? `${guide.prompts[0]}\n\n(prose, not bullets — the writer makes the bullets)` : ""
        }
        className="mt-1 w-full rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 p-3 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-stone-400"
      />

      {value.includes("TODO") && (
        <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">
          Still carries a bootstrap TODO. Those are notes from the import, not content — delete
          them once you have answered them.
        </p>
      )}
    </div>
  );
}
