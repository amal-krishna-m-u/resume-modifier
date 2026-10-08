# Future scope

Deliberately **not built yet**. Each item says what exists today, what is missing, and why it waits. Recorded 2026-10-09.

## F1 — API-key providers as first-class backends (no CLI)

**Today.** The Claude and Codex backends drive local programs (`claude`, `codex`) that must be installed and logged in. The OpenAI-compatible backend takes an API key, but only from an environment variable, and it has no prompt caching. `ANTHROPIC_API_KEY` is honoured by the Claude SDK backend, and the `claude` program has its own Vertex and Bedrock switches. None of that is tested here or exposed in Settings.

**To build.**
- A native **Anthropic API** runner, with prompt caching on the corpus prefix (the knowledge base is resent on every call, so caching is what keeps a metered API affordable).
- A **Vertex AI** runner for Claude (Google credentials, project, region) and, if wanted, **Bedrock**.
- A native **OpenAI** runner with structured outputs, and a **Gemini** runner.
- A **key field in Settings**, stored outside the repository (OS keychain, or a `0600` file) and never returned by the API; the UI shows only "key set".
- Per-provider **cost reporting** (tokens × price) so a metered run shows what it cost.

**Why it waits.** The CLI backends work on an existing subscription at no marginal cost, which suits a single local user. Keys only matter once someone wants to run without the CLIs, or host it.

## F2 — Hosting

**Today.** Single user, single machine by design: the server binds `127.0.0.1` only (AC-R1.2), has no authentication, and keeps its data in local files and a local git repository.

**To build.**
- A login in front of the API and UI, and HTTPS.
- A configurable bind address that refuses to listen on a non-loopback interface unless authentication is on.
- A persistent volume for `kb/`, `runs/`, `applications/`, `traces/`, `evals/`.
- F1, so no CLI has to be installed and logged in on the server.
- Backups for `kb/`, which has no remote on purpose (OQ-9).

**Multi-user** is a separate and much larger step: per-user knowledge bases, per-user model credentials, and moving the file-and-git storage to something with access control. Not planned.

**Why it waits.** Every constraint above is a deliberate privacy decision for one person's career record; relaxing them needs the pieces together, not one at a time.

## F3 — Smaller known gaps

- Job-link ingestion (paste text or upload a file today; a URL is not fetched).
- Recall's tag proposals are not routed into the knowledge-base chat inbox.
- `claude_cli` and `openai_compat` show start/finish and tokens in the live view, but no streaming text or reasoning.
- The Langfuse compose file in `ops/langfuse/` has not been run (no Docker on the development machine).
- Eval cases need a person to review them before scores mean quality rather than consistency.
