# resume-tailor

A local, single-user system that tailors a resume to a job description from a complete personal career knowledge base — then shows what matched, what's missing, and lets you revise by chat before exporting a PDF.

**Status:** implementation underway. The specification is complete and merged; the knowledge base layer is built. See [Milestones](#milestones).

## The problem it solves

Manual resume tailoring fails in two directions. Over-claiming is visible and gets punished in interviews. **Silent omission** — a genuinely relevant project you simply didn't think of while editing — is invisible, and you never learn which application it cost you.

Eliminating silent omission is the point. Everything else is mechanism.

## Read in this order

| Document | What it answers |
|---|---|
| [docs/PRD.md](docs/PRD.md) | What is being built, for whom, and what counts as done |
| [docs/traceability.md](docs/traceability.md) | Did every stated requirement survive into the design? **Review this first.** |
| [docs/spec-01-knowledge-base.md](docs/spec-01-knowledge-base.md) | How career data is stored and edited |
| [docs/spec-02-agent-pipeline.md](docs/spec-02-agent-pipeline.md) | The five agents and why selection reads everything |
| [docs/spec-03-runtime-auth.md](docs/spec-03-runtime-auth.md) | Subscription vs API key, and the spike that decides it |
| [docs/spec-04-api-and-ui.md](docs/spec-04-api-and-ui.md) | Endpoints, the write path, the screens |
| [docs/spec-05-latex-rendering.md](docs/spec-05-latex-rendering.md) | LaTeX generation and PDF output |
| [docs/spec-06-provider-backends.md](docs/spec-06-provider-backends.md) | Running on providers other than Claude |
| [docs/spec-07-applications-and-tracker.md](docs/spec-07-applications-and-tracker.md) | Application archive, tracker, dual contact sets |
| [docs/open-questions.md](docs/open-questions.md) | What's still undecided and what each answer blocks |

`traceability.md` is the fast review surface: every requirement appears there alongside the user's own words that produced it. If something asked for isn't in that table, the PRD is incomplete.

## Three invariants

These are load-bearing, and all three are easy to regress toward their opposite:

1. **Tags never gate retrieval.** Selection reads the full text of every fact. Tags exist for human navigation, audit trails, and second-pass validation. A missing tag must never cause a silent miss.
2. **The knowledge base is the source of truth; LaTeX is generated from it.** Agents edit structured data, never `.tex`.
3. **Every claim traces to a recorded fact.** A validator with no stake in making the resume look good cuts anything that doesn't.

## How it works

Three views: what the agents do, how the code is layered, and where everything
runs. All three are current as of M4 — the pipeline is built; the API and UI
are not.

### The multi-agent pipeline

```mermaid
flowchart TD
    JD["Job posting"] --> ANALYST["<b>Analyst</b><br/>atomic requirements<br/><i>explicit + implicit</i>"]
    ANALYST --> REQ["requirements.json"]
    KB[("kb/ — full corpus")]

    subgraph passes["Two independent passes — run concurrently"]
        direction LR
        SELECTOR["<b>Selector</b><br/>judge every fact<br/>on its body text"]
        RECALL["<b>Recall</b><br/>adversarial:<br/>find what was missed"]
    end

    REQ --> SELECTOR
    REQ --> RECALL
    KB -.->|"full bodies, never an index"| SELECTOR
    KB -.->|"full bodies, never an index"| RECALL
    SELECTOR -.->|"--sequential only:<br/>which facts, <b>not why</b>"| RECALL

    SELECTOR --> MERGE{{"<b>merge</b><br/>union + provenance<br/><i>disagreements surfaced,<br/>never resolved</i>"}}
    RECALL --> MERGE

    MERGE --> SELECTION["merged.json<br/><i>chosen_by: both / selector / recall</i>"]
    MERGE --> GAPS["gap-report.md<br/><i>absent · weak · tag proposals</i>"]

    SELECTION --> WRITER["<b>Writer</b><br/>compress and retarget<br/><i>narrow input, by design</i>"]
    WRITER --> DRAFT["draft.json"]
    DRAFT --> VALIDATOR["<b>Validator</b><br/>grounding only"]
    VALIDATOR --> VALIDATION["validation.json<br/><i>cuts · warnings</i>"]

    VALIDATION --> REVIEW["Review"]
    REVIEW --> CHAT["Chat revision"]
    CHAT -.->|"always re-validates"| WRITER
    REVIEW --> RENDER["LaTeX → PDF<br/><i>one per contact set</i>"]

    classDef agent fill:#1f3a5f,stroke:#4a90d9,stroke-width:2px,color:#fff
    classDef artifact fill:#2d2d2d,stroke:#888,color:#eee
    classDef store fill:#3d2b1f,stroke:#c08040,color:#fff
    class ANALYST,SELECTOR,RECALL,WRITER,VALIDATOR agent
    class REQ,SELECTION,DRAFT,VALIDATION,GAPS artifact
    class KB store
```

**Why two selection passes.** The failure this product exists to prevent is
silent omission: a relevant fact that no model ever read, whose absence nobody
notices. One pass with a tag filter in front of it would be cheaper and would
reintroduce exactly that. So both passes read every word of every fact, and
where they disagree the review screen says so rather than a merger picking a
winner.

By default the two run **concurrently**, which halves wall-clock time on the
stage that dominates it; Recall then judges the corpus blind. With
`--sequential` it instead receives the Selector's picks — *which* facts, never
*why* — because a second pass handed the first pass's argument mostly agrees
with it.

**Why the Writer gets less.** Selection and writing have opposite information
needs. Selection wants full fidelity, because relevance hides in any clause.
Writing wants a narrow input, because irrelevant material makes bullets
blander. Conflating them produces an index-based selector, which is the
omission again.

### Architecture

```mermaid
flowchart TB
    subgraph entry["Entry points"]
        CLI["<b>rt</b> CLI<br/><i>kb · render · tailor · health</i>"]
        API["FastAPI<br/><i>127.0.0.1 only</i><br/><b>M5</b>"]
        UI["React + Vite<br/><b>M6</b>"]
    end

    subgraph core["Core"]
        PIPELINE["<b>pipeline/</b><br/>orchestrator · merge · artifacts · report"]
        AGENTS["<b>agents/</b><br/>5 specs + editable prompts"]
        RENDER["<b>render/</b><br/>document · latex · escape · compile"]
        APPS["<b>applications/</b><br/>slug · snapshot · tracker<br/><b>M7</b>"]
    end

    subgraph kb["Knowledge base"]
        LOADER["<b>kb/</b><br/>schema · loader · validate · write"]
        FILES[("kb/*.md + *.yaml<br/><i>plain files, own git repo</i>")]
        CACHE[(".cache/index.json<br/><i>derived, never authoritative</i>")]
    end

    subgraph runtime["runtime/ — one interface, five backends"]
        BASE["<b>RunnerBackend</b><br/><i>string in, JSON out</i>"]
        SDK["claude_sdk<br/><i>default</i>"]
        CLIB["claude_cli"]
        CODEX["codex_cli"]
        COMPAT["openai_compat<br/><i>Ollama, OpenRouter, …</i>"]
        FAKE["fake<br/><i>tests</i>"]
    end

    UI --> API
    API --> PIPELINE
    CLI --> PIPELINE
    CLI --> RENDER
    PIPELINE --> AGENTS
    PIPELINE --> RENDER
    PIPELINE --> BASE
    AGENTS --> BASE
    BASE --> SDK & CLIB & CODEX & COMPAT & FAKE
    PIPELINE --> LOADER
    RENDER --> LOADER
    APPS --> RENDER
    LOADER --> FILES
    LOADER -.->|rebuildable| CACHE

    classDef future fill:#2d2d2d,stroke:#666,stroke-dasharray:4 3,color:#999
    classDef iface fill:#1f3a5f,stroke:#4a90d9,stroke-width:2px,color:#fff
    class API,UI,APPS future
    class BASE iface
```

Two seams carry the weight. **`RunnerBackend`** is the only thing the pipeline
knows about a model, so swapping Claude for a local model is configuration, not
a change to any agent. **`Document`** is the only thing the template knows
about content, so the baseline render and a tailored run produce the same shape
and the template knows about neither.

Note what is *not* here: no vector store, no database of record, no queue. The
knowledge base is plain files; `.cache/` is derived and can be deleted at any
time.

### Where it runs

There is no infrastructure to provision. This is a single-user tool that runs
entirely on one machine — no server, no container, no cloud account, and no
Terraform to write. The only thing crossing the network is the model API call
made by the user's own authenticated session.

```mermaid
flowchart LR
    subgraph machine["Your machine — everything below is local"]
        direction TB

        subgraph proc["Processes"]
            RT["<b>rt</b> / uvicorn<br/><i>binds 127.0.0.1 only</i>"]
            TECT["tectonic<br/><i>LaTeX → PDF</i>"]
        end

        subgraph disk["Filesystem"]
            KBR[("<b>kb/</b><br/>own git repo<br/><b>no remote</b>")]
            RUNS[("runs/<br/><i>disposable</i>")]
            APPSD[("applications/<br/><i>permanent archive</i>")]
            EVID[("evidence/")]
        end

        subgraph repo["Public git repo"]
            CODE["code · docs · templates"]
        end
    end

    SUB["Anthropic API<br/><i>your subscription session</i>"]
    BOARD["Job board<br/><i>optional, for URL ingest</i>"]

    RT -->|"the only outbound<br/>model traffic"| SUB
    RT -.->|optional| BOARD
    RT --> TECT
    RT <--> KBR
    RT --> RUNS
    RT --> APPSD
    RT -.-> EVID
    CODE -.->|"gitignores all<br/>of the above"| KBR

    classDef remote fill:#3d2b1f,stroke:#c08040,color:#fff
    classDef private fill:#1f3a2d,stroke:#4ad98a,color:#fff
    class SUB,BOARD remote
    class KBR,RUNS,APPSD,EVID private
```

The green stores never leave the machine. `kb/` is versioned by its own git
repository that has **no remote** — full history locally, nothing published —
because the public repo would otherwise carry the complete career record. The
single action that would undo that is `git -C kb remote add`.

## Local setup

```bash
brew install tectonic                 # LaTeX engine, ~70MB (needed from M2 on)
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Then create the knowledge base. **It is not in this repository**, by design:

```bash
mkdir -p kb/{roles,facts,projects,blogs,education,certifications,awards}
cp kb/identity.example.yaml kb/identity.yaml
$EDITOR kb/identity.yaml              # name, contact sets, links
git init kb                           # versioning, with NO remote — see below
.venv/bin/rt kb validate
```

### Why `kb/` has its own git repository

This repository is **public**. `kb/` holds a complete career record — every
employer, location, date and achievement, plus the working notes written
against them. None of that should be indexable under its owner's name.

But the design needs git: history, diff and one-click revert come from commits
rather than from a hand-rolled undo stack (AC-R8.3, [spec-04 §3](docs/spec-04-api-and-ui.md)),
and three different writers touch those files — the browser, a text editor, and
agent-proposed changes.

So `kb/` is versioned by its own repository, which has **no remote**. Both
properties hold at once: full history locally, nothing published. The outer
`.gitignore` excludes everything under `kb/` except `identity.example.yaml`,
which a fresh clone needs.

**Do not add a remote to `kb/`.** That single action is what would publish the
career record, and nothing else in the design prevents it.

### What else stays local

| Path | Why |
|---|---|
| `kb/` | The career record, and `identity.yaml`'s contact details |
| `applications/` | Complete resumes, job descriptions, third-party referrer names |
| `runs/` | Disposable tailoring output; reproducible from `kb/` |
| `chats/` | Your knowledge-base conversations — your career in your own words |
| `evidence/` | Certificates and letters |
| `*.pdf`, `*.docx` | Source resumes dropped in for bootstrapping |

Durability for all of these comes from being plain files in a backed-up home
directory, not from version control ([open-questions OQ-3](docs/open-questions.md)).

## Using it

```bash
.venv/bin/rt serve                       # the web interface, 127.0.0.1 only
.venv/bin/rt kb validate                 # the ten rules of spec-01 §4
.venv/bin/rt kb stats                    # corpus size — the numbers OQ-2 tracks
.venv/bin/rt health                      # backend, auth, Tectonic, context fit

.venv/bin/rt render                      # the whole KB, no agents involved
.venv/bin/rt tailor --file posting.txt   # the five-agent pipeline
.venv/bin/rt tailor --resume <run-id>    # continue from the last completed stage

.venv/bin/rt apply <run-id> --company Acme --role "Backend Engineer"
.venv/bin/rt applications list --live    # the tracker
.venv/bin/rt applications verify         # re-hash the archive, report drift
```

A `tailor` run writes everything it did into `runs/<id>/`: the requirements it
extracted, both selection passes, the merge, the draft, the validation, the gap
report, and a PDF per contact set. Nothing is hidden, and nothing there is a
source of truth — it is all reproducible from `kb/` plus the posting.

## Milestones

| | Milestone | State |
|---|---|---|
| M1 | Knowledge base: schema, loader, validation, bootstrap | **done** |
| M2 | LaTeX template and PDF output | **done** |
| M3 | Runner backends behind one interface | **done** |
| M4 | The five-agent pipeline, end to end from a CLI | **done** |
| M5 | FastAPI write path and SSE | **done** |
| M6 | React UI | **done** |
| M7 | Application archive and tracker | **done** |
| M8 | Self-hosted Langfuse tracing and prompt evals ([OQ-10](docs/open-questions.md)) | next |

## After you apply

```bash
.venv/bin/rt apply <run-id> --company Acme --role "Backend Engineer" --job-id R1234
```

Promotion is **explicit**. Exporting a PDF does not create a record — you often
export just to look at something. This is the moment the system can know the
content became permanent, so it is the moment it freezes.

What freezes: the rendered resumes, the job description, and a content snapshot
holding the **full text of every fact as it read at send time**. What stays
editable: status, interview stages, referral details, notes.

The snapshot embeds fact bodies rather than referencing them, because a
reference would resolve to the *current* fact. The knowledge base moves on, and
a resume regenerated from today's corpus is not the resume that was sent —
preparing for an interview against reconstructed content is worse than having
no record, because it is confidently wrong.

`rt applications verify` re-hashes everything and reports drift. The archive
lives in `applications/`, company-first, and is gitignored: it holds complete
resumes, job descriptions and third-party referrer names.

## Updating your knowledge base

Three ways, and all three write through the same validated path:

| Mode | Use it for |
|---|---|
| **Form** | A structured editor: tag chips with alias search, depth and visibility with explanations, metric rows |
| **Raw** | The file itself, for anything the form cannot express |
| **Chat** | Describe what you did in your own words; the assistant proposes the entry |

Chat is a third tab beside Form and Raw in every entry, and **Add by chat** covers things that aren't about one entry (a new job, say). It never writes anything. Each proposal is shown as exactly what would change — a new entry in full, or for an update only the part that differs — with its validation result visible before you decide. **Nothing is saved until you accept**, and accepting lands as a commit in your local `kb/` repository, so it can be reverted.

The assistant records only what you tell it. It asks when it needs a number or a date rather than guessing, defaults `depth` to `working` rather than flattering you, and prefers adding to an existing entry over creating a near-duplicate. It cannot delete.

## The run screen

The compiled resume stays on screen while you work. **Revise** (chat), **Sources**, **Matches** and **Gaps** sit beside it.

- **Direct / Referral** only switches which version you are looking at, in place. Nothing downloads until you press **Download PDF** or **.tex**.
- **PDF | LaTeX** shows either one inline; the LaTeX has a copy button for pasting into Overleaf.
- Revising keeps the last verified PDF in view and disables downloads until the new draft's claims have been re-checked.
- Each answer shows what actually changed — a diff computed from the two drafts, beside the model's own account and any claims the validator cut.

## The web interface

```bash
cd web && npm install && npm run build   # once
.venv/bin/rt serve                       # http://127.0.0.1:8000
```

One process, one port: the API under `/api`, the built bundle served from the
same origin, so there is no CORS configuration to get wrong. In development
`cd web && npm run dev` runs Vite on 5173 and proxies `/api` to the Python
process.

Export is disabled until the review screen has been opened (AC-R4.3). The whole
point is that you see what was cut and what is missing before anything leaves
the machine.

## Tests

```bash
.venv/bin/pytest -q            # live-backend tests are excluded by default
.venv/bin/pytest -q -m live    # hits a real model backend
.venv/bin/ruff check src tests
```

## Validating the docs

```bash
python3 docs/validate_docs.py
```

Stdlib only. Fails on untraced requirements, acceptance criteria without Given/When/Then, specs covering undefined requirements, orphaned criteria, missing source quotes, and dead links.

## Next step

M8: self-hosted Langfuse tracing and a prompt eval set
([OQ-10](docs/open-questions.md)) — so "did prompt v2 select better than v1"
becomes answerable, which is what OQ-6 (which model for which agent) is waiting
on.
