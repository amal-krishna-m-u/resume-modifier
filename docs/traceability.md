# Traceability Matrix

Every requirement maps to the user's own words, to testable acceptance criteria, and to the spec section that implements it. Checked mechanically by [`validate_docs.py`](validate_docs.py).

**Read this table first when reviewing the PRD.** If something you asked for isn't here in your own words, the PRD is incomplete. If a row's quote doesn't support its requirement, the requirement drifted and should be struck.

| ID | Requirement | Source quote | Acceptance criteria | Specs |
|---|---|---|---|---|
| R1 | Runs locally, used through a browser | "a tool … that runs locally in my system" / "a UI interphase that runs locally in our system through browser" | AC-R1.1, AC-R1.2, AC-R1.3 | [spec-04 §1](spec-04-api-and-ui.md) |
| R2 | JD input as pasted text or link | "when I input the job description or the link" | AC-R2.1, AC-R2.2, AC-R2.3 | [spec-04 §3](spec-04-api-and-ui.md) |
| R3 | Tailors from own experience and skills | "it should be able to tailor the resume to that job description based on my experince and skills" | AC-R3.1, AC-R3.2 | [spec-02 §3](spec-02-agent-pipeline.md) |
| R4 | Shows matches and missing items before export | "the things that are matching and also list things I am missing - all of these will first be shown in the UI interphase after the creation" | AC-R4.1, AC-R4.2, AC-R4.3 | [spec-04 §6.3](spec-04-api-and-ui.md) |
| R5 | Chat to revise after generation | "then I should be able to chat with the tool and make changes and explain things that can be added or changes I need for removing" | AC-R5.1, AC-R5.2, AC-R5.3 | [spec-02 §4](spec-02-agent-pipeline.md), [spec-04 §6.4](spec-04-api-and-ui.md) |
| R6 | PDF download | "after that this should be able to download in pdf formate" | AC-R6.1, AC-R6.2 | [spec-05 §7](spec-05-latex-rendering.md) |
| R7 | LaTeX is the base format; existing PDF rebuilt in it | "first it should convert the current one to overleaf formate and intial everytihng should be in overleaf" | AC-R7.1, AC-R7.2, AC-R7.3 | [spec-05 §1](spec-05-latex-rendering.md), [spec-05 §3.1](spec-05-latex-rendering.md), [spec-05 §4](spec-05-latex-rendering.md) |
| R8 | Local knowledge base, easily editable | "I also need a local knowledgebase that is easily editable" | AC-R8.1, AC-R8.2, AC-R8.3 | [spec-01 §1](spec-01-knowledge-base.md), [spec-01 §5](spec-01-knowledge-base.md), [spec-04 §5](spec-04-api-and-ui.md) |
| R9 | Full career record, used only as required | "I want to store my entire carreer history , my blogs, my projects etc and use them as it's required and only as it's required" | AC-R9.1, AC-R9.2, AC-R9.3 | [spec-01 §2](spec-01-knowledge-base.md), [spec-01 §3.4](spec-01-knowledge-base.md) |
| R10 | Tags on all content, for JD connection and human validation | "along with every content there should be tag options so it's easier to connect to jd and lesser chance of missing things out" / "tags are there in case to validate for the human and for better understanding when you check for second time" | AC-R10.1, AC-R10.2, AC-R10.3, AC-R10.4 | [spec-01 §3.6](spec-01-knowledge-base.md), [spec-02 §3.3](spec-02-agent-pipeline.md), [spec-04 §6.5](spec-04-api-and-ui.md) |
| R11 | Semantic selection over full content, never tag-gated | "it shouldn't be just checking the tags , tags is just one part, we might miss a tag but for the jd it's might be a required project,experinece or skills with in an job experinece so it should be taken ,should not just focus on the tags" | AC-R11.1, AC-R11.2, AC-R11.3, AC-R11.4 | [spec-02 §1](spec-02-agent-pipeline.md), [spec-02 §2](spec-02-agent-pipeline.md), [spec-02 §3.2](spec-02-agent-pipeline.md), [spec-01 §6](spec-01-knowledge-base.md) |
| R12 | Multi-agent: creating, validating, reviewing | "This should be a multi agentic system with multiple agaents creating validating and going through things that matters" | AC-R12.1, AC-R12.2, AC-R12.3 | [spec-02 §3](spec-02-agent-pipeline.md), [spec-02 §4](spec-02-agent-pipeline.md) |
| R13 | KB updated by chat and by manual web-UI editing | "I should have option to talk and update my knowledge also manually edit knowledge base through intractive web UI" | AC-R13.1, AC-R13.2, AC-R13.3, AC-R13.4 | [spec-04 §2](spec-04-api-and-ui.md), [spec-04 §6.5](spec-04-api-and-ui.md), [spec-04 §6.6](spec-04-api-and-ui.md) |
| R14 | Light React frontend, Python backend and SDK | "I need a light frontend framework like react or a better optimised version and python for backend and sdk" | AC-R14.1, AC-R14.2 | [spec-04 §1](spec-04-api-and-ui.md), [spec-04 §4](spec-04-api-and-ui.md), [spec-04 §7](spec-04-api-and-ui.md), [spec-06 §1](spec-06-provider-backends.md) |
| R15 | Subscription-preferred, pluggable runtime | "using claude sdk and the current subscription I have to leverage" | AC-R15.1, AC-R15.2, AC-R15.3 | [spec-03 §2](spec-03-runtime-auth.md), [spec-03 §3](spec-03-runtime-auth.md), [spec-06](spec-06-provider-backends.md) |
| R16 | Text chat in v1; voice deferred | "I should have option to talk and update my knowledge" — scoped to text chat by decision 2026-10-06 | AC-R16.1, AC-R16.2 | [PRD §3](PRD.md) |
| R17 | Two contact sets; both resumes rendered every run | "I need two set of contanct details mail 1 and number 1 ,mail 2 and number 2 … when resume is created I need it to be created with both set ,so I can use one resume for referal and one i can apply right away without any referals" | AC-R17.1, AC-R17.2, AC-R17.3, AC-R17.4 | [spec-01 §2.1](spec-01-knowledge-base.md), [spec-05 §7](spec-05-latex-rendering.md), [spec-07 §8](spec-07-applications-and-tracker.md) |
| R18 | Deterministic, collision-free application archive | "dowlonading the resumes should create a folder with jd, details and etc and download both cvs under that folders should be unqiue … comapny/jobrole-jobid-date/cv1-referal,cv2-nonreferal … So when I open the folder I can easier identify the cvs under the companies I have applied" | AC-R18.1, AC-R18.2, AC-R18.3, AC-R18.4, AC-R18.5 | [spec-07 §2](spec-07-applications-and-tracker.md), [spec-07 §3](spec-07-applications-and-tracker.md), [spec-07 §7](spec-07-applications-and-tracker.md) |
| R19 | Application tracker | "I need a tracker I can use by default .In which I can track the job I have applied resume used and if referals recived the referals recived" | AC-R19.1, AC-R19.2, AC-R19.3, AC-R19.4, AC-R19.5 | [spec-07 §4](spec-07-applications-and-tracker.md), [spec-07 §6](spec-07-applications-and-tracker.md), [spec-04 §6.6](spec-04-api-and-ui.md) |
| R20 | Immutable content snapshot | "also which keep track of the resumes content so if I get any further comminications for further stages I can refer to the content I have used to apply" | AC-R20.1, AC-R20.2, AC-R20.3, AC-R20.4 | [spec-07 §1](spec-07-applications-and-tracker.md), [spec-07 §5](spec-07-applications-and-tracker.md), [spec-04 §6.7](spec-04-api-and-ui.md) |

## Reverse check — did we invent anything?

Every requirement above traces to a quote. Three items in the specs are **not** user-stated and are design decisions made during discussion; they are listed here so they're visible as additions rather than smuggled in as requirements:

| Addition | Origin | Justification |
|---|---|---|
| `depth` field (expert/working/exposure) | Proposed by assistant, 2026-10-06 | Structural guard against over-claiming; serves R3 honestly |
| `visibility` field (public/nda/private) | Proposed by assistant, 2026-10-06 | User's record includes EY client work; prevents NDA leakage |
| Two independent full-corpus passes (Selector + Recall) | Proposed by assistant, 2026-10-06 | The mechanism that delivers R11's "lesser chance of missing things out" |
| Git versioning of every KB write (AC-R8.3) | Proposed by assistant, 2026-10-06 | You asked for "easily editable", not versioned. Added because three writers (browser, text editor, agents) touch the same files, and undo/diff come free from git rather than needing an undo stack |
| `profiles/` saved tag weightings | Proposed by assistant, 2026-10-06 | Reframes the existing PDF as one rendering of the KB rather than a separate document |
| Proposals inbox for agent-suggested KB changes | Proposed by assistant, 2026-10-06 | Required to keep AC-R13.3's single write path honest — agents propose, they never write |
| `runs/` vs `applications/` boundary; promotion as an explicit step | Proposed by assistant, 2026-10-07 | You asked for a tracker and an archive, not for a distinction between attempts and submissions. Added because exporting a PDF to look at it must not create an application record, and because freezing requires a defined moment |
| Integrity hashing and read-only artifacts | Proposed by assistant, 2026-10-07 | R20 asks to keep track of content used. Hashing is what makes that claim checkable rather than assumed |
| `order` field on entries | Proposed by assistant, 2026-10-07 | Baseline rendering needs a deterministic bullet order, and sorting by id put the financial ledger above the trading engine because `l` precedes `t`. Author-chosen, and ignored once the Writer orders by relevance |
| `group` field on `skills.yaml` rows | Proposed by assistant, 2026-10-07 | The source resume groups skills into four editorial groups. Taxonomy facets describe what a term *is*, which is not how a reader wants them grouped on a page |
| Inline `**bold**` in fact bodies and prose | Proposed by assistant, 2026-10-07 | The source resume bolds key figures inside prose and bullets; reproducing its design (R7) needs a way to express that. Deliberately the only markup supported |
| The `curator` agent and its conversation scoping | Required by AC-R13.2; mechanism proposed by assistant, 2026-10-08 | AC-R13.2 says chat proposes a reviewable diff. Proposals as *changes* rather than files, per-entry conversations and dependency ordering are design decisions that keep "chat" from becoming a way around the checks |
| A computed diff in every revision answer | Proposed by assistant, 2026-10-08 | R5 asks for chat revision. Replying "draft revised" cannot tell you whether a request was honoured, partly honoured or ignored; the model's account is a claim, the diff is a fact |
| `meta.json` and display titles for runs | Proposed by assistant, 2026-10-08 | The web form never supplied a role, so runs were folder-named `…-untitled`. A display title is separate from the permanent folder name |
| Refusing export mid-revision (`409 run_busy`) | Proposed by assistant, 2026-10-08 | Between the Writer and Validator finishing, the draft is new and the verdict is old; exporting then could hand over unchecked claims (Q1) |
| `ghosted` as a distinct terminal status | Proposed by assistant, 2026-10-07 | Silence is the most common outcome; folding it into `rejected` destroys the only signal about which channels work |

If any of these is unwanted it can be removed without affecting a stated requirement, with two exceptions: the two-pass design, which R11 depends on, and the proposals inbox, which R13.3 depends on.

## Quality requirement coverage

| ID | Quality requirement | Enforced by |
|---|---|---|
| Q1 | Zero fabricated claims | [spec-02 §3.5](spec-02-agent-pipeline.md) Validator; `selection.json` audit trail |
| Q2 | Recall over precision | [spec-02 §3.3](spec-02-agent-pipeline.md) Recall pass; [spec-05 §6](spec-05-latex-rendering.md) no silent truncation |
| Q3 | Honest strength signalling | [spec-01 §3.3](spec-01-knowledge-base.md) `depth`; [spec-02 §3.4](spec-02-agent-pipeline.md) Writer ceiling |
| Q4 | Data outlives the tool | [spec-01 §1](spec-01-knowledge-base.md) plain files + git |

## Risk coverage

| Risk | Mitigation lives in |
|---|---|
| RK-1 auth uncertainty | [spec-03 §1](spec-03-runtime-auth.md), [spec-03 §3](spec-03-runtime-auth.md), [spec-06](spec-06-provider-backends.md) |
| RK-2 rate limits | [spec-02 §6](spec-02-agent-pipeline.md), [spec-03 §4](spec-03-runtime-auth.md) |
| RK-3 blocked job boards | [spec-04 §3](spec-04-api-and-ui.md) |
| RK-4 LaTeX fidelity drift | [spec-05 §4](spec-05-latex-rendering.md) |
| RK-5 optimistic `depth` | [spec-02 §3.5](spec-02-agent-pipeline.md), [spec-04 §6.3](spec-04-api-and-ui.md) |
| RK-6 corpus growth | [spec-02 §2](spec-02-agent-pipeline.md), [open-questions.md](open-questions.md) OQ-2 |
| RK-7 NDA leakage | [spec-01 §3.3](spec-01-knowledge-base.md), [spec-05 §7](spec-05-latex-rendering.md) |
| RK-8 dual-identity duplicate applications | [spec-07 §8](spec-07-applications-and-tracker.md) |
