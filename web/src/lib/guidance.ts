/** What each entry type is for, and what a good body contains.
 *
 * The hardest part of building a knowledge base is not the form — it is
 * knowing what to write. A blank textarea produces one compressed sentence,
 * which is exactly what the bootstrap left behind and exactly why the gap
 * report keeps reporting "matched, but not strongly": the fact is real and its
 * body is too thin to carry the claim.
 *
 * So the body field asks questions instead of showing an empty box.
 */

export interface TypeGuide {
  label: string;
  blurb: string;
  /** Questions that elicit the detail selection needs. */
  prompts: string[];
  /** Roughly how much body text is enough, in words. */
  target: number;
  example?: string;
}

export const GUIDES: Record<string, TypeGuide> = {
  role: {
    label: "Job or engagement",
    blurb:
      "A container, not an achievement. It supplies the heading, dates and organisation that selected facts render beneath.",
    prompts: [
      "What did the team or organisation actually do?",
      "What was your scope — what did you own versus contribute to?",
      "How big was the team, and where did you sit in it?",
      "What changed about the role over time?",
    ],
    target: 60,
  },
  fact: {
    label: "Achievement",
    blurb:
      "One thing you did, written so it can be selected on its own. This is the unit the pipeline picks from — most of your knowledge base should be these.",
    prompts: [
      "What did you build or change? Be specific about the system.",
      "What made it hard? The constraint, the failure mode, the thing that nearly didn't work.",
      "What decision did you make, and what did you reject?",
      "What measurably changed? Put the figure in `metrics` as well.",
      "What would you say if an interviewer pushed on this for ten minutes?",
    ],
    target: 120,
    example:
      "Order book held in memory with a write-ahead path to Postgres; margin recalculated per fill rather than per tick, which is what kept p99 under 100ms at 2k connections. Backpressure handled by dropping stale market-data frames while never dropping order-state frames.",
  },
  project: {
    label: "Project",
    blurb: "Something you built outside a job, or alongside one.",
    prompts: [
      "What does it do, and who was it for?",
      "What was technically interesting about it?",
      "Is it live, used, or abandoned? Say which — honestly.",
      "What would you do differently now?",
    ],
    target: 90,
  },
  blog: {
    label: "Writing",
    blurb:
      "A post or talk. Selection never fetches the URL, so the body has to carry the argument.",
    prompts: [
      "What is the argument, in two or three sentences?",
      "What capability does writing it demonstrate?",
      "Did anyone respond to it, use it, or disagree with it?",
    ],
    target: 70,
  },
  education: {
    label: "Education",
    blurb: "A degree or formal course.",
    prompts: [
      "What was the coursework that actually matters to the work you do?",
      "Final-year or capstone project — what was it?",
      "Grade or standing, if it helps.",
    ],
    target: 50,
  },
  certification: {
    label: "Certification",
    blurb: "A credential someone else issued.",
    prompts: [
      "What does it actually cover?",
      "When was it issued, and does it expire?",
      "Is there a verification link or credential id?",
    ],
    target: 40,
  },
  award: {
    label: "Award or recognition",
    blurb: "Something you were given.",
    prompts: [
      "What is it given for, and by whom?",
      "How often is it awarded, and to how many people?",
      "What specifically did the citation refer to?",
    ],
    target: 50,
  },
};

export const DEPTH_HELP: Record<string, string> = {
  expert:
    "Can be framed as deep ownership, architecture, or leading the work. Use this when you could defend every decision for an hour.",
  working:
    "Can be framed as having built and shipped it, competently. The honest default.",
  exposure:
    "Can be mentioned, never framed as expertise. The writer is forbidden from saying 'experienced in' or 'proficient with'.",
};

export const VISIBILITY_HELP: Record<string, string> = {
  public: "Can appear in an exported resume.",
  nda: "Selectable, and visible to you here — it is your history. The renderer refuses to export it.",
  private: "Never exported, never shown outside this machine.",
};

/** Words in a body, ignoring the bootstrap's TODO comments. */
export function bodyWords(body: string): number {
  return body.split("<!--")[0]!.trim().split(/\s+/).filter(Boolean).length;
}

export type Thinness = "empty" | "thin" | "ok";

/** Whether a body is likely to carry a claim under scrutiny.
 *
 * Not a quality judgement — just length. A one-line body is a resume bullet,
 * and a resume bullet is what the writer is supposed to *produce*, not consume.
 */
export function thinness(body: string, type: string): Thinness {
  const words = bodyWords(body);
  const target = GUIDES[type]?.target ?? 80;
  if (words === 0) return "empty";
  return words < target * 0.5 ? "thin" : "ok";
}

export function hasTodo(body: string): boolean {
  return body.includes("TODO");
}
