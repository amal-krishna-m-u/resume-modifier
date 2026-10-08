import type { IndexRow } from "./types";

/** A role as a person reads it: "Associate Software Engineer 2 · EY GDS · Aug 2025 – Feb 2026".
 *
 * Section headings in the draft were the raw entry ids — `EY-ASE2`,
 * `CUSAT-BTECH-IT` — which are keys, not labels. */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function month(value?: string): string | null {
  if (!value) return null;
  if (value === "present") return "Present";
  const [year, m] = value.split("-");
  const index = Number(m) - 1;
  return index >= 0 && index < 12 ? `${MONTHS[index]} ${year}` : value;
}

export function range(dates: IndexRow["dates"]): string | null {
  if (!dates) return null;
  const start = month(dates.start);
  const end = month(dates.end);
  if (!end || end === start) return start;
  return `${start} – ${end}`;
}

export interface RoleLabel {
  title: string;
  org?: string;
  dates?: string;
}

export function labelFor(id: string | undefined, entries: IndexRow[]): RoleLabel | null {
  if (!id) return null;
  const row = entries.find((entry) => entry.id === id);
  if (!row) return null;
  return {
    title: row.title,
    org: row.org ?? undefined,
    dates: range(row.dates) ?? undefined,
  };
}

/** Most recent first, `present` above everything — how every reader scans a resume. */
export function byRecency(a: IndexRow, b: IndexRow): number {
  const key = (row: IndexRow) =>
    row.dates?.end === "present" ? "9999-99" : (row.dates?.end ?? row.dates?.start ?? "");
  return key(b).localeCompare(key(a));
}
