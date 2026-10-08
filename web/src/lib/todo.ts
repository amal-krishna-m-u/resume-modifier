/** The bootstrap leaves an HTML comment in each body saying what to add.
 *
 * Shown raw inside the writing area it looks like markup to delete, yet it is
 * the most useful text on the page — specific to this exact entry ("chunking
 * and embedding choices, how retrieval quality was evaluated…"). So it is
 * lifted out into its own callout and written back on save, untouched, until
 * the user says it has been answered. */
const TODO_RE = /\n*<!--\s*TODO:?([\s\S]*?)-->\s*$/;

export function splitTodo(body: string): { text: string; note: string | null } {
  const match = body.match(TODO_RE);
  if (!match) return { text: body, note: null };
  const note = match[1]!.replace(/\s+/g, " ").trim();
  return { text: body.slice(0, match.index).trimEnd(), note: note || null };
}

export function joinTodo(text: string, note: string | null): string {
  return note ? `${text.trimEnd()}\n\n<!-- TODO: ${note} -->` : text;
}
