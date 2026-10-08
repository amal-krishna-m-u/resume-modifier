# Contributing

Thanks for looking. This is a local, single-user tool, so most useful contributions are a **new backend**, a **better prompt**, a **bug fix**, or **clearer docs**. Planned larger pieces (API-key providers, hosting) are in [docs/future-scope.md](docs/future-scope.md); say you're picking one up before starting.

Questions or ideas: open an issue, or reach the maintainer — see [CONTRIBUTORS.md](CONTRIBUTORS.md).

## Set up

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cd web && npm install && npm run build && cd ..
brew install tectonic        # PDF rendering
cp kb/identity.example.yaml kb/identity.yaml
```

See the README's *Local setup* for the full version.

## Before you open a pull request

```bash
.venv/bin/pytest -q                  # live-backend tests are excluded by default
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
python3 docs/validate_docs.py
cd web && npx tsc --noEmit && npm run build
```

One branch per change, one pull request per branch, against `main`.

## Privacy rules (the important ones)

This repository is **public**, and the tool works on someone's complete career record. Never commit:

- anything under `kb/` (it has its own git repository with no remote), `runs/`, `applications/`, `chats/`, `traces/`, `evals/`, `evidence/`;
- `kb/identity.yaml`, `resume-tailor.toml`, `ops/langfuse/.env`, or any resume PDF;
- real postings, real names, emails or phone numbers in tests, docs or fixtures. Use invented data.

`.gitignore` covers these, but check `git status` before `git add -A`. Do not give `kb/` a git remote.

## Design rules a change must not break

1. **Tags never gate retrieval.** Selection reads every fact in full.
2. **The knowledge base is the source of truth;** LaTeX is generated, agents never edit `.tex`.
3. **Every claim traces to a recorded fact.** Chat and revisions always go through the Validator.
4. **Agents propose; people write.** Nothing reaches `kb/` except through the validated write path.
5. **Tracing stays self-hosted.** A non-local Langfuse host is refused on purpose.

## Adding a backend

Implement the `RunnerBackend` protocol in `src/resume_tailor/runtime/`, register it in `runtime/__init__.py` (`BACKENDS`, `BACKEND_INFO`, `_construct`), and add tests that need no network. Add a `@pytest.mark.live` case beside the existing ones. Model every failure you can reproduce: an auth error must name the credential it expected, and a provider's own error text must reach the user, not "reply was not JSON".

## Changing a prompt

Prompts are editable files in `src/resume_tailor/agents/prompts/`. Build an eval case from a real run (`rt eval build`), run `rt eval run --label before`, make the change, run `rt eval run --label after`, and put `rt eval compare before after` in the pull request. Without that, "this prompt is better" is an opinion.

## Commits

Short imperative subject, and a body that says *why*. Tests should state the failure they prevent; this codebase's tests carry the reasoning.
