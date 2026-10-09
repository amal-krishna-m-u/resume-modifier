# PRD — Local Resume Tailoring System

**Status:** Draft for approval
**Owner:** the repository owner
**Date:** 2026-10-06
**Companion specs:** [KB](spec-01-knowledge-base.md) · [Agents](spec-02-agent-pipeline.md) · [Runtime](spec-03-runtime-auth.md) · [API/UI](spec-04-api-and-ui.md) · [LaTeX](spec-05-latex-rendering.md)
**Validation:** [traceability.md](traceability.md) · [open-questions.md](open-questions.md)

---

## 1. Problem

Tailoring a resume per job application is high-value and manually expensive. The current state is a single PDF, hand-tuned for AI developer roles. It represents a fraction of the actual career record, and every new role type means re-editing a document by hand from memory.

Manual tailoring fails in two directions, and they are not equally visible:

- **Over-claiming** — stretching experience to fit a posting. Visible, and punished in interviews.
- **Silent omission** — a genuinely relevant project, achievement, or skill exists but doesn't come to mind while editing, so it never makes it onto the page.

The second is the expensive one, because nothing surfaces it. You never learn which application failed because you forgot to mention the ACID ledger work. **Eliminating silent omission is the product's primary purpose**; everything else is mechanism.

A generic LLM "tailor my resume" prompt actively makes the first problem worse — it invents flattering experience, because that is what optimizes the apparent quality of its output.

## 2. User and context

Single user, single machine. One person's career data, their own Claude account, no other users ever. Job-searching while employed, so the data includes NDA-bound client work that must not leak into exports. Technical: comfortable editing YAML and Markdown by hand, and will do so — the UI is not the only writer.

This is a personal tool, not a product. It is never hosted, never multi-tenant, never serves another person's request.

## 3. Goals

- **G1** — No relevant experience is silently omitted from a tailored resume.
- **G2** — No claim appears on a resume that isn't traceable to a recorded fact.
- **G3** — The full career record accumulates in one durable, hand-editable place and outlives the tool.
- **G4** — Producing a tailored, compiled PDF from a job description takes minutes, not an evening.

### Non-goals (v1)

| Not doing | Why |
|---|---|
| Multi-user / hosted | Single-user personal tool. Hosting changes the auth and legal position entirely. |
| LinkedIn / Indeed / Workday scraping | They block server-side fetching; defeating that violates their ToS. Paste the text. |
| Cover letter generation | Deferred to v2. The KB makes it easy later. |
| Voice / speech-to-text | Deferred to v2. "Talk to the tool" in v1 means text chat. |
| Vector search / embeddings | Not warranted below ~500 KB entries. See [spec-02](spec-02-agent-pipeline.md). Revisit per [open-questions.md](open-questions.md) OQ-2. |
| Auto-apply / job-board integration | Out of scope. |

## 4. Core loop

```
JD (paste or URL)
   │
   ├─▶ Fit        — local, no model: closest existing resume + sketched gaps
   │                 reuse / fill gaps (Writer+Validator) / full pipeline
   │
   ├─▶ Analyst    — parse into required / preferred / implicit requirements
   │
   ├─▶ Selector   — read FULL corpus, choose relevant facts, record why
   ├─▶ Recall     — read FULL corpus independently, challenge omissions
   │        └─ union of both passes, with disagreements surfaced
   │
   ├─▶ Writer     — frame selected facts as bullets for this JD
   ├─▶ Validator  — every claim traces to a fact, or it is cut
   │
   ├─▶ UI review  — matched items + gap report shown BEFORE export
   ├─▶ Chat       — revise, add, remove, explain
   │
   └─▶ Render     — KB data → Jinja2 → .tex → Tectonic → PDF
```

Nothing exports until the human has seen the match list and the gap report.

## 5. Functional requirements

Each requirement carries the user's own words that produced it. If a requirement's quote doesn't support it, the requirement is wrong.

---

### R1 — Local execution, browser interface

> "a tool … that runs locally in my system" / "a UI interphase that runs locally in our system through browser"

The system runs entirely on the user's machine and is used through a browser.

**AC-R1.1** — Given the app is started, When the user opens `http://127.0.0.1:8000`, Then the full UI loads from the local process with no external hosting dependency.
**AC-R1.2** — Given the server starts, When it binds its socket, Then it binds `127.0.0.1` only and is unreachable from other machines on the LAN.
**AC-R1.3** — Given a tailoring pass on pasted JD text, When the pipeline runs, Then the only outbound network request is the model API call — KB content, blog snapshots, fonts, and frontend assets are all read from local disk.

### R2 — Job description input by text or link

> "when I input the job description or the link"

Accepts a pasted JD or a URL.

**AC-R2.1** — Given pasted JD text, When the user submits it, Then a run is created and the text is stored verbatim at `runs/<slug>/posting.txt`.
**AC-R2.2** — Given a URL from a fetchable source (company careers page, Greenhouse, Lever), When submitted, Then the posting text is extracted and the user sees it for confirmation before the run proceeds.
**AC-R2.3** — Given a URL that blocks fetching or returns a login wall (LinkedIn, Indeed, Workday), When submitted, Then the UI reports the fetch failed and prompts for a paste — it never proceeds on partial or wrong content silently.

### R3 — Tailoring from the user's own record

> "it should be able to tailor the resume to that job description based on my experince and skills"

Output content derives from the knowledge base and the job description, never from model priors about what the role "should" contain.

**AC-R3.1** — Given a JD and a populated KB, When a run completes, Then every bullet in the draft is linked to ≥1 KB fact ID.
**AC-R3.2** — Given a JD requiring a technology absent from the KB, When the run completes, Then that technology appears in the gap report and appears nowhere in the resume body.

### R4 — Show matches and gaps before export

> "the things that are matching and also list things I am missing - all of these will first be shown in the UI interphase after the creation"

**AC-R4.1** — Given a completed run, When the review screen renders, Then it shows each JD requirement with its matched KB facts and the selection reason.
**AC-R4.2** — Given a completed run, When the review screen renders, Then it shows a gap report of JD requirements with no matching fact, each marked `absent` or `weak`.
**AC-R4.3** — Given a completed run, When the user has not yet opened the review screen, Then no PDF export is offered.

### R5 — Post-generation chat revision

> "then I should be able to chat with the tool and make changes and explain things that can be added or changes I need for removing"

**AC-R5.1** — Given a completed run, When the user sends a chat instruction, Then the draft updates and the change is shown as a diff against the previous version.
**AC-R5.2** — Given a chat instruction to add a claim with no supporting KB fact, When processed, Then the system refuses to write it into the resume and instead offers to create the backing KB fact first.
**AC-R5.3** — Given a chat session, When the user reloads the page, Then the conversation is restored from `runs/<slug>/chat.jsonl`.

### R6 — PDF download

> "after that this should be able to download in pdf formate"

**AC-R6.1** — Given an approved draft, When the user clicks export, Then a compiled PDF downloads.
**AC-R6.2** — Given a LaTeX compile failure, When export is attempted, Then the UI shows the actionable compile error and the offending source line — never a silent failure or an empty file.

### R7 — LaTeX as the base format

> "first it should convert the current one to overleaf formate and intial everytihng should be in overleaf"

The existing PDF's layout is reproduced in LaTeX, and LaTeX is the rendering format for all output. **Clarification carried from design discussion:** "Overleaf format" is LaTeX; Overleaf is an editor. The deliverable is a `.tex` file that compiles locally and can be pasted into Overleaf unmodified.

**AC-R7.1** — Given the existing resume PDF, When the LaTeX template renders the same content, Then the output meets every fidelity target in [spec-05 §4](spec-05-latex-rendering.md) — section order, single-column layout, header structure, contact line, heading style, and bold-lead-in bullets — verified by side-by-side page images.
**AC-R7.2** — Given any run, When the user requests the source, Then a self-contained `.tex` is downloadable and compiles in Overleaf without edits.
**AC-R7.3** — Given KB content containing LaTeX-special characters (`& % $ # _ { } ~ ^ \`), When rendered, Then they are escaped and the document compiles.

### R8 — Local, easily editable knowledge base

> "I also need a local knowledgebase that is easily editable"

**AC-R8.1** — Given the KB, When inspected on disk, Then it is plain Markdown and YAML files, readable and editable without the app running.
**AC-R8.2** — Given a KB file edited in an external editor while the app is running, When the file is saved, Then the open UI reflects the change without a manual refresh.
**AC-R8.3** — Given any KB write, When it completes, Then it is a git commit, and the prior state is recoverable.

### R9 — Complete career record, used selectively

> "I want to store my entire carreer history , my blogs, my projects etc and use them as it's required and only as it's required"

The KB is a superset of any resume. It holds roles, achievements, projects, blogs, education, certifications, and awards in more detail than any single resume would use.

**AC-R9.1** — Given the KB, When entries are added, Then roles, facts, projects, blogs, education, certifications, and awards are each first-class and independently selectable.
**AC-R9.2** — Given a run, When the draft is assembled, Then it contains only facts selected for this JD — the KB is never rendered wholesale.
**AC-R9.3** — Given a blog or external project entry, When stored, Then a local text snapshot is kept alongside the URL so selection never depends on a live fetch.

### R10 — Tags on all content

> "along with every content there should be tag options so it's easier to connect to jd and lesser chance of missing things out" / "tags are there in case to validate for the human and for better understanding when you check for second time"

Tags serve human navigation, audit, and second-pass validation. **They are not the retrieval mechanism** — see R11.

**AC-R10.1** — Given any KB entry, When edited, Then tags can be assigned from a controlled vocabulary with autocomplete, including matches on alias terms.
**AC-R10.2** — Given a tag not in the vocabulary, When the user assigns it, Then the system prompts to add it to `taxonomy.yaml` rather than silently creating an orphan tag.
**AC-R10.3** — Given a completed run, When the review screen renders, Then each selected fact displays its tags so the user can sanity-check the match.
**AC-R10.4** — Given the Recall pass finds a fact relevant on content whose tags do not reflect that relevance, When the run completes, Then a tag addition is proposed for user approval.

### R11 — Semantic selection over full content, never tag-gated

> "it shouldn't be just checking the tags , tags is just one part, we might miss a tag but for the jd it's might be a required project,experinece or skills with in an job experinece so it should be taken ,should not just focus on the tags"

This is a hard invariant, not a preference.

**AC-R11.1** — Given a run, When selection executes, Then the selecting agent receives the full body text of every KB fact, not a summary or index projection.
**AC-R11.2** — Given a fact relevant to the JD on its body text but carrying no matching tag, When a run executes, Then that fact is still eligible and can be selected.
**AC-R11.3** — Given any stage of the pipeline, When candidates are processed, Then no mechanical filter (tag match, keyword, top-k) removes any fact from consideration. Ranking is permitted; removal before model judgment is not.
**AC-R11.4** — Given a role containing several achievements, When selection executes, Then each achievement is independently selectable without pulling in its siblings.

### R12 — Multi-agent pipeline

> "This should be a multi agentic system with multiple agaents creating validating and going through things that matters"

Five agents: Analyst, Selector, Recall, Writer, Validator. Full contracts in [spec-02](spec-02-agent-pipeline.md).

**AC-R12.1** — Given a run, When it executes, Then selection is performed by two independent full-corpus passes (Selector, Recall) with separate instructions.
**AC-R12.2** — Given the two passes disagree, When the run completes, Then the disagreement is surfaced in the review UI rather than resolved silently.
**AC-R12.3** — Given a draft, When the Validator runs, Then any claim not traceable to a source fact is removed and reported.

### R13 — KB updated by chat and by manual UI editing

> "I should have option to talk and update my knowledge also manually edit knowledge base through intractive web UI"

**AC-R13.1** — Given the KB browser, When the user edits an entry in the structured form or the raw editor, Then the change is validated and written to the file.
**AC-R13.2** — Given a chat message describing new experience, When processed, Then the system proposes a KB entry as a reviewable diff and writes it only on approval.
**AC-R13.3** — Given any KB write from any source (UI form, raw editor, chat-proposed diff), When it executes, Then it passes through one shared write path with identical validation.
**AC-R13.4** — Given a file changed on disk since the UI loaded it, When the user saves, Then the write is rejected with a conflict and both versions are shown — no silent overwrite.

### R14 — React frontend, Python backend

> "I need a light frontend framework like react or a better optimised version and python for backend and sdk"

Vite + React + TypeScript + Tailwind; FastAPI backend.

**AC-R14.1** — Given the repo, When the frontend is built, Then it is served as static files by the same FastAPI process — one command, one port.
**AC-R14.2** — Given a running pipeline, When agents progress, Then the UI streams status over SSE rather than polling.

### R15 — Subscription-preferred, pluggable runtime

> "using claude sdk and the current subscription I have to leverage"

Subscription auth is preferred. Because enforcement behavior is unverified, the runtime is an interface with two backends and the choice is made by an empirical spike. See [spec-03](spec-03-runtime-auth.md).

**AC-R15.1** — Given the runtime layer, When a backend is selected by config, Then switching between CLI-subprocess and Agent-SDK backends requires no change to agent or pipeline code.
**AC-R15.2** — Given the spike script, When run, Then it reports definitively whether the Agent SDK accepts the local subscription session.
**AC-R15.3** — Given an auth failure at runtime, When it occurs, Then the error states which backend failed and what credential it expected — not a raw stack trace.

### R16 — Text chat in v1; voice deferred

> "I should have option to talk and update my knowledge" — scoped to text chat for v1 by decision 2026-10-06.

**AC-R16.1** — Given v1, When the user interacts conversationally, Then it is via text chat.
**AC-R16.2** — Given the v2 backlog, When reviewed, Then speech-to-text KB dictation is recorded as a deferred item with its implementation sketch.

### R17 — Two contact sets, both resumes rendered every run

> "I need two set of contanct details mail 1 and number 1 ,mail 2 and number 2. i will use one to apply for jobs with referal and other for jobs without referal (for same jd) and when resume is created I need it to be created with both set ,so I can use one resume for referal and one i can apply right away without any referals"

**AC-R17.1** — Given `kb/identity.yaml` defines named contact sets, When it is loaded, Then each set carries its own email and phone and is selectable by name.
**AC-R17.2** — Given a completed run with two contact sets configured, When export runs, Then two resumes are produced — one per set — differing only in the contact block.
**AC-R17.3** — Given two contact sets, When a run executes, Then the agent pipeline runs once, not twice, since the tailored content is identical across sets.
**AC-R17.4** — Given only one contact set is configured, When export runs, Then exactly one resume is produced and no error occurs.

### R18 — Deterministic, collision-free application archive

> "dowlonading the resumes should create a folder with jd, details and etc and download both cvs under that folders should be unqiue so maybe a combinstion of jobrole,jobid if avaialbe,date of applicatoin can be used to create the folder. it should be something like comapny/jobrole-jobid-date/cv1-referal,cv2-nonreferal something like this hirearcy . So when I open the folder I can easier identify the cvs under the companies I have applied"

**AC-R18.1** — Given an application is recorded, When its folder is created, Then the path is `applications/<company>/<role>-<discriminator>-<date>/` holding the job description, both resumes, and the tracker record.
**AC-R18.2** — Given a posting with no job ID, When the folder name is derived, Then a stable 6-character hash of the job URL or posting text is used, producing the same name on a re-run of the same posting.
**AC-R18.3** — Given two applications that would resolve to the same folder name, When the second is created, Then it is suffixed `-2` and no existing folder is overwritten.
**AC-R18.4** — Given a company name containing path separators, punctuation, or non-ASCII characters, When slugified, Then the result is a safe lowercase path component, and casing alone never produces two folders for one company.
**AC-R18.5** — Given applications exist across several months, When `_views/by-month/` is regenerated, Then each month lists symlinks to that month's applications without altering the canonical tree.

### R19 — Application tracker

> "I need a tracker I can use by default .In which I can track the job I have applied resume used and if referals recived the referals recived"

**AC-R19.1** — Given recorded applications, When the tracker is opened, Then each row shows company, role, application date, status, which contact set was sent, and whether a referral was received.
**AC-R19.2** — Given the tracker, When the user filters by company, status, month, or referral received, Then only matching applications are listed.
**AC-R19.3** — Given an application, When the user updates its status, adds an interview stage, or records referral details, Then the change is written to `application.yaml` and the frozen artifacts are untouched.
**AC-R19.4** — Given the derived index is deleted, When the tracker is next opened, Then it is rebuilt from the `application.yaml` files with no data loss.
**AC-R19.5** — Given an `application.yaml` edited by hand, When a reindex runs, Then the tracker reflects the edit.

### R20 — Immutable content snapshot

> "also which keep track of the resumes content so if I get any further comminications for further stages I can refer to the content I have used to apply"

**AC-R20.1** — Given an application is recorded, When the snapshot is written, Then it contains the rendered bullets, their source fact IDs, and the full fact body text as it read at that moment.
**AC-R20.2** — Given a KB fact is edited after an application was recorded, When that application's snapshot is viewed, Then it shows the content as sent, not the current content.
**AC-R20.3** — Given a recorded application, When its integrity is verified, Then stored hashes are compared against the artifacts on disk and any drift is reported.
**AC-R20.4** — Given an application detail view, When opened, Then the snapshot is shown alongside the current KB so divergence since sending is visible.

---

## 6. Quality requirements

**Q1 — Zero fabricated claims.** Every claim in an exported resume traces to a KB fact ID. This is enforced by the Validator (R12) and verifiable after the fact: `selection.json` records the mapping, so any bullet can be audited back to its source. A tailoring tool that invents experience is worse than no tool, because the failure surfaces in an interview.

**Q2 — Recall over precision in selection.** When uncertain whether a fact is relevant, the pipeline includes it for human review rather than dropping it. Over-inclusion costs the user ten seconds on the review screen; omission is invisible and permanent. This asymmetry justifies the cost of two full-corpus passes.

**Q3 — Honest strength signalling.** The `depth` field (`expert` / `working` / `exposure`) constrains how strongly the Writer may frame a claim. An `exposure` fact may be listed but not described as expertise.

**Q4 — The data outlives the tool.** The KB stays plain files in git. If this application is abandoned, the career record remains readable and useful.

## 7. Constraints

- Server binds `127.0.0.1` exclusively.
- No KB content leaves the machine except in model API calls made by the user's own authenticated session.
- Model usage shares rate limits with the user's interactive Claude Code sessions (if on the subscription backend).
- `kb/` is written only through the validated write path; a run may *propose* KB changes but never applies them without approval.
- NDA-flagged content (`visibility: nda`) must never appear in an export.

## 8. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| RK-1 | Agent SDK rejects subscription OAuth | Core premise fails | Pluggable runtime + CLI-subprocess fallback; spike before building ([spec-03](spec-03-runtime-auth.md)) |
| RK-2 | Multi-agent runs exhaust subscription rate limits | Tool unusable at the moment it's needed | Corpus in cached prompt prefix; agent count held at five; per-run token budget reported in UI |
| RK-3 | Major job boards block URL ingestion | R2 partially unmet | Paste path is primary and always available; explicit failure message (AC-R2.3) |
| RK-4 | LaTeX output drifts from the familiar layout | Resume looks unfamiliar or unprofessional | Visual diff against the original PDF using `pdftoppm` during template development |
| RK-5 | `depth` fields filled in optimistically | Over-claiming returns through the back door | `depth` surfaced in the review UI next to each bullet; Validator flags `exposure` facts framed as expertise |
| RK-6 | Corpus growth degrades selection quality | Silent omissions return as the KB gets large | Track corpus token count; OQ-2 defines the threshold for revisiting semantic search |
| RK-7 | NDA content reaches an export | Professional and legal exposure | `visibility` enforced at render time, not selection time, and asserted in tests |
| RK-8 | Applying twice to one role under different contact details trips ATS deduplication, or reads as duplicate applying to a recruiter who sees both | Application discarded, or a poor impression | Not a technical problem to solve. The tracker records `contact_set_sent` per application so the user knows which identity reached which company, and decides for themselves ([spec-07 §8](spec-07-applications-and-tracker.md)) |

## 9. Appendix — current resume content inventory

Extracted from the owner's source resume, which stays local (1 page). This is the bootstrap seed for the KB and the fidelity reference for the LaTeX template.

**Identity:** held locally in `kb/identity.yaml` — name, headline, location, phone, email, and profile links. That file is gitignored as the only PII-dense file in the project ([spec-01 §2](spec-01-knowledge-base.md)); `kb/identity.example.yaml` is committed and shows its shape. See [README → Local setup](../README.md#local-setup).

**Sections present:** Summary · Technical Skills (4 groups) · Professional Experience (3 roles) · Internships (2) · Education & Certifications

**Roles:** Independent Full-Stack & Cloud Consultant, xpar.in, Bengaluru (Feb 2026–present) · Associate Software Engineer 2 (Python & AI), EY GDS, Kochi (Aug 2025–Feb 2026) · Associate Software Engineer 1, EY GDS, Kochi (Jul 2024–Aug 2025)

**Atomic facts identified:** 9 achievement bullets across 3 roles, plus 2 internships, 1 degree, 1 award, 1 certification — the initial `facts/` population.

**Metrics appearing:** 40% faster delivery cycles · sub-100ms latency · 2,000+ concurrent users · 60% less manual intake · >50% less triage time · 95%+ first-pass fix rate · 35% faster queries · CGPA 9.13/10

**Layout characteristics to reproduce:** single column, full-width · name centered as header with role subtitle · contact line pipe-separated · bold lead-in phrase per bullet followed by detail · section headings in small caps, rule-separated.
