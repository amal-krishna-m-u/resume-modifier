import type { ReactNode } from "react";

/** Render `**bold**` and `*italic*` as real emphasis.
 *
 * The Writer emits the same two markers the LaTeX renderer understands — they
 * are the only two the source resume uses — and the review screen was printing
 * them literally, so every bolded figure showed as `**sub-100ms**`.
 *
 * Built as React nodes rather than HTML. The text comes from a model reading
 * knowledge-base content, and `dangerouslySetInnerHTML` would make whatever it
 * emitted markup.
 */
const TOKEN = /\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\*)\*(?=\S)([^*]+?)(?<=\S)\*(?!\*)/g;

export function Inline({ text }: { text: string }): ReactNode {
  const parts: ReactNode[] = [];
  let cursor = 0;
  let key = 0;

  for (const match of text.matchAll(TOKEN)) {
    const at = match.index ?? 0;
    if (at > cursor) parts.push(text.slice(cursor, at));
    if (match[1] !== undefined) {
      parts.push(
        <strong key={key++} className="font-semibold text-stone-900 dark:text-stone-50">
          {match[1]}
        </strong>,
      );
    } else if (match[2] !== undefined) {
      parts.push(<em key={key++}>{match[2]}</em>);
    }
    cursor = at + match[0].length;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}

/** Plain text with the markers removed, for places that cannot hold markup. */
export function stripMarkup(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, "$1").replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, "$1");
}
