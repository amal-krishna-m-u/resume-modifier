# Open Questions

Each entry names the decision it blocks and when it must be answered. An open question with no blocked decision is just trivia and doesn't belong here.

---

## OQ-1 — Does the Agent SDK accept a Pro/Max subscription session? — **RESOLVED: yes**

**Resolved:** 2026-10-06, by `spike/auth_probe.py`.
**Decision:** `spec-03` default backend → **`sdk`**.

```
claude-agent-sdk   0.2.163
claude CLI         2.1.291
ANTHROPIC_API_KEY  absent (run under `env -u ANTHROPIC_API_KEY`)

SDK path           ok, reply "OK",  8,131 input tokens (lean config)
CLI path (control) ok, reply "OK",  7,994 input tokens
```

Re-run with **every** `CLAUDE_CODE_*` session variable also stripped — in case the
subprocess was inheriting credentials from the surrounding Claude Code session —
and it still succeeded at 7,618 tokens. That rules out the main confound.

Two incidental corrections to the commonly-repeated description of this mechanism:

- **`~/.claude/.credentials.json` does not exist on this machine.** macOS stores
  the subscription credential in the Keychain. Any backend that probes for that
  file to decide whether subscription auth is available will wrongly conclude it
  is not.
- The CLI here lives at `~/.local/bin/claude`, not an npm global path, so
  `npm install -g @anthropic-ai/claude-code` is one install route rather than a
  requirement.

**Policy, unchanged by this result:** the test shows the SDK *works*; it does not
change what is *permitted*. Personal single-user use is ordinary individual use
([spec-03 §1](spec-03-runtime-auth.md)). Distributing a tool that routes other
people's requests through these credentials is not, which is why
[spec-06](spec-06-provider-backends.md) exists.

---

## OQ-7 — Does the ChatGPT **Free** plan include Codex **CLI** access?

**Blocks:** whether Codex is a viable zero-cost backend for other people using this tool. Does not block anything for the repo owner.
**Resolve by:** before documenting Codex as a free option for others.

Verified 2026-10-06 on this machine: `codex exec --json --skip-git-repo-check` works, model `gpt-5.5`, 272,000-token context, strict-JSON prompt returned a bare parseable object. 18,365 input tokens of harness overhead per call.

**What that does not prove:** the plan this account is on. OpenAI's pricing page states Codex is *"included in your ChatGPT Free, Go, Plus, Pro, Business, Edu, or Enterprise plan"*, while listing CLI access among what the paid tiers add. So Free-tier **CLI** eligibility is unconfirmed, and a working test on a possibly-paid account cannot settle it.

Needs a test from an actual Free account before Codex is documented as a free path for others.

---

## OQ-10 — Tracing: Langfuse — **RESOLVED: built (M8), self-hosted, opt-in**

**Decided:** 2026-10-07. Scheduled as M8, after the archive and tracker.

Per-run artifacts on disk already answer *what did this run do*: every stage
writes its JSON to `runs/<id>/` and nothing is hidden. What they do not answer
is *did prompt v2 select better than v1*, because comparing runs means diffing
directories by hand and there is no place for an eval set to live.

That question is the one blocking [OQ-6](#oq-6--which-model-for-which-agent)
(which model for which agent) and it will block any serious prompt tuning, so
the tooling has to exist before either can be settled.

**Hard constraint: self-hosted, never the managed cloud.** [PRD §7](PRD.md)
says no knowledge-base content leaves the machine except in the model API call
made by the user's own session. Traces carry the full corpus in the prompt —
every employer, date and achievement — so sending them to a hosted endpoint
would breach that constraint far more comprehensively than the thing the
constraint was written about.

**Resolved 2026-10-09 (M8):**

- **Opt-in or default?** Both, split by where the data goes. A local JSONL log
  (`traces/`, gitignored) is on by default because it never leaves the machine.
  Langfuse is off until `[observability] langfuse = true`, because it needs a
  server the person runs.
- **Where to wrap?** `RunnerBackend`, once (`TracedBackend`), so Claude, Codex
  and the rest are traced identically. Run and case identity travel in a
  contextvar, so no agent or pipeline signature changed.
- **Where do eval cases live?** In `evals/`, gitignored: they are real postings
  plus the facts a resume drew on. They cannot be committed to a public repo.
- **Self-hosted is enforced, not requested.** The Langfuse host is checked and
  anything but loopback, a private address or a LAN/compose name is refused, as
  is `*.langfuse.com`.
- **What an eval measures.** Selection (recall of expected facts, forbidden
  picks, stability against the baseline) and a validator probe: a fabricated
  bullet is injected into a real draft and the Validator must cut or flag it.
  Cases built from a run are `reviewed: false` — their scores mean *consistent
  with that run*, not *correct*, until a person edits and marks them reviewed.
- **Not verified here:** the Docker compose file in `ops/langfuse/` has not been
  run (no Docker on the development machine). The exporter is verified against a
  stub of Langfuse's OTLP endpoint, which proves a generation leaves the
  process, not that a real server renders it. `rt trace status` is the check.

---

## OQ-2 — At what corpus size does full-corpus selection stop working?

**Blocks:** whether semantic search is ever needed; the point at which [spec-02 §2](spec-02-agent-pipeline.md) must be revisited.
**Resolve by:** ongoing measurement, not up front.

Current design reads every fact on every selection pass, which is right at ~150 facts (~18K tokens) and clearly wrong at 5,000. The threshold is unknown and depends on both cost and whether selection quality degrades with corpus size — the second being the one that actually matters, since degradation is silent.

**Signals to watch:** corpus token count (reported by `/api/health`); per-run cost; whether Recall starts finding more omissions as the corpus grows, which would indicate the Selector is losing track rather than that Recall is working well.

Provisional trigger to re-examine: **500 entries or 100K corpus tokens**, whichever first. Picked as an order-of-magnitude marker, not a measured threshold.

---

## OQ-3 — Is `runs/` git-tracked? — **RESOLVED: no**

**Resolved:** 2026-10-07, forced by the application archive and a public repository.

Neither `runs/` nor `applications/` is tracked. `applications/` holds complete resumes carrying both contact sets, job descriptions, and third-party referrer names; the repository is public, so tracking it would publish all of that permanently ([spec-07 §10](spec-07-applications-and-tracker.md)).

The earlier leaning — track text artifacts, ignore binaries — was written before the archive existed and assumed `runs/` held only scratch output. It would now leak PII.

Durability comes from plain files in a backed-up home directory, not from version control. The archive is designed to survive the tool, not the repository.

---

## OQ-4 — One page or two?

**Blocks:** Writer length budget; overflow behavior in [spec-05 §6](spec-05-latex-rendering.md).

The current resume is one page at ~2.2 years of experience, which is conventional. As the record grows, forcing one page starts cutting relevant content — and silent cutting to fit is the exact failure the product exists to prevent.

**Needs a policy:** is one page a hard constraint, a default with per-run override, or a target the user resolves manually each time via the overflow report? Current spec assumes the third, which is the safest default but asks the most of the user.

---

## OQ-5 — Can NDA-flagged content appear in any export?

**Blocks:** `visibility` enforcement strictness in [spec-05 §7](spec-05-latex-rendering.md).

Current spec: `visibility: nda` content is selectable and visible in review (it's the user's own history) but the renderer refuses to emit it.

**Unresolved:** whether there's a legitimate middle case — generalizing an NDA-bound achievement so it conveys capability without identifying the client ("built document ingestion for a Fortune 500 financial services client"). That is normal resume practice and is probably wanted, but it needs an explicit mechanism: likely a `generalized` field holding a pre-approved safe phrasing, with the renderer emitting that instead of refusing.

Until decided, the strict rule stands. Over-blocking is recoverable; leaking isn't.

---

## OQ-6 — Which model for which agent?

**Blocks:** cost per run; nothing structural.

[spec-02 §5](spec-02-agent-pipeline.md) assigns provisionally: strongest model for Analyst, Selector, Recall, and Writer; a smaller model for the Validator, which is a checking task.

**Untested assumption:** that a smaller model is adequate for validation. It might be *better* — less inclined to rationalize a claim into being supported — or materially worse at noticing subtle unsupported inference. Worth an A/B once there's a real corpus and a few real drafts to check against.

---

## OQ-9 — Is `kb/` tracked in the public repository? — **RESOLVED: no, it has its own remote-less repo**

**Resolved:** 2026-10-07, when the bootstrap produced real content.

`kb/` is versioned by its own git repository, which has no remote. The project
repository is public and ignores everything under `kb/` except
`identity.example.yaml`, which a fresh clone needs.

The original design said `kb/` was git-tracked, and isolating `identity.yaml`
was treated as sufficient privacy. That held only while `kb/` contained an
example file. With the real bootstrap in place it does not: the career record —
employers, locations, dates, achievements, and the working notes written against
them — would be published and indexed under the owner's name. The notes are the
worse half; they are candid by design and read badly out of context.

Dropping git instead was the alternative, and it costs more than it looks:
AC-R8.3's undo, the history and revert endpoints in
[spec-04 §3](spec-04-api-and-ui.md), and reviewable agent-proposed diffs all come
from commits. A separate remote-less repository keeps all of that and publishes
none of it.

This is the same correction as OQ-3, arriving for the same reason: a tracking
decision made before the content existed stopped being safe once it did.

**The residual risk is one command.** `git -C kb remote add …` publishes
everything, and no other part of the design prevents it. Documented in
[spec-01 §2.2](spec-01-knowledge-base.md) and the README; worth a
`/api/health` warning once that endpoint exists.

---

## OQ-8 — Retention: does an application record ever get archived or deleted?

**Blocks:** nothing yet. Becomes real after a year or two of use.

The archive grows monotonically and nothing prunes it. Each application is a few hundred KB, so a thousand of them is well under a gigabyte — storage is not the concern.

**The actual question is signal, not space.** A tracker listing 800 applications, 700 of them long-dead, is harder to use than one showing the 30 that are live. Options: a `hidden` flag that the default view filters out, a year-based move into `applications/_archive/<year>/`, or nothing at all with reliance on status filters.

**Leaning:** status filters are probably sufficient, since `ghosted` and `rejected` already separate dead from live. Revisit once there is enough real history to tell whether the tracker actually feels cluttered — guessing now would be designing for an imagined problem.

---

## Resolved

| # | Question | Decision | Date |
|---|---|---|---|
| — | Voice input in v1? | No — text chat only; voice deferred to v2 | 2026-10-06 |
| — | Single PRD or PRD + specs? | PRD + five companion specs | 2026-10-06 |
| — | Commit to one runtime backend? | No — pluggable interface, spike decides the default | 2026-10-06 |
| — | Vector DB for the KB? | No — full-corpus selection; revisit per OQ-2 | 2026-10-06 |
| — | Fall back to Antigravity CLI? | No — Codex verified working; Antigravity free tier is ~20 req/day | 2026-10-06 |
| — | Tags as the retrieval mechanism? | No — tags are for humans and audit; selection is semantic over full content | 2026-10-06 |
| — | LaTeX as source of truth? | No — KB is source of truth; LaTeX is generated | 2026-10-06 |
