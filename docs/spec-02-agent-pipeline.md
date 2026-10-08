# Spec 02 — Agent Pipeline

**Covers:** R3, R4, R11, R12, Q1, Q2, Q3
**Related:** [PRD](PRD.md) · [KB](spec-01-knowledge-base.md) · [Runtime](spec-03-runtime-auth.md)

---

## 1. The invariant

> **No mechanical filter may remove a fact from consideration. Ranking is permitted; removal before model judgment is not.** (AC-R11.3)

Every design choice below follows from this. The failure this prevents: a fact relevant on its content but missing a tag gets filtered out before any model reads it, and the omission is permanent and invisible. Tag matching, keyword search, and top-k truncation are all instances of this failure.

Where this bites is cost — reading the full corpus twice per run is more tokens than filtering first. That cost is accepted and mitigated by caching (§6), not by filtering.

## 2. Why selection reads everything

Selection and writing have opposite information needs:

| Stage | Needs | Because |
|---|---|---|
| Selection | **Full fidelity** — every word of every fact | Relevance can hide in any clause; a summary is a lossy projection and the loss is invisible |
| Writing | **Narrow input** — only selected facts | Irrelevant material makes bullets blander and less targeted |

Conflating these produces an index-based selector, which reintroduces silent omission. The Selector therefore receives full fact bodies; only the Writer receives a narrowed set.

**Scale check:** ~150 facts at ~120 tokens each ≈ 18K tokens; 400 facts ≈ 50K. One pass per agent, twice per run, cached across runs in a session. Affordable. The threshold at which this stops being true is tracked in [open-questions.md](open-questions.md) OQ-2.

## 3. The five agents

```
                    ┌─────────────┐
   JD text ────────▶│   Analyst   │──── requirements.json
                    └─────────────┘
                           │
          ┌────────────────┴────────────────┐
          ▼                                 ▼
   ┌─────────────┐                   ┌─────────────┐
   │  Selector   │                   │   Recall    │     both read the
   │ full corpus │                   │ full corpus │     FULL corpus,
   └─────────────┘                   └─────────────┘     independently
          │                                 │
          └────────────────┬────────────────┘
                           ▼
                    selection.json  (union + disagreements)
                           │
                    ┌─────────────┐
                    │   Writer    │──── draft.json
                    └─────────────┘
                           │
                    ┌─────────────┐
                    │  Validator  │──── validation.json (claims cut + reasons)
                    └─────────────┘
                           │
                    ▼ review UI → chat → render
```

### 3.1 Analyst

**Input:** JD text. **Output:** `requirements.json`.

Decomposes the posting into atomic, individually-matchable requirements. The useful work is extracting *implicit* requirements — "you'll own the service end to end" implies on-call and production ownership, which the posting never states as a bullet.

```json
{
  "role_title": "Senior ML Platform Engineer",
  "seniority": "senior",
  "requirements": [
    {"id": "RQ1", "text": "Production RAG systems at scale",
     "kind": "required", "source": "explicit", "quote": "3+ years building RAG..."},
    {"id": "RQ2", "text": "On-call ownership of production services",
     "kind": "implicit", "source": "inferred", "quote": "you'll own the service end to end"}
  ],
  "signals": {"domain": "fintech", "stack": ["python", "aws"], "team_stage": "early"}
}
```

`kind` ∈ `required` | `preferred` | `implicit`. Every explicit requirement carries the `quote` it came from — so a wrong requirement is traceable to a misreading rather than being unexplainable.

### 3.2 Selector

**Input:** `requirements.json` + **full corpus**. **Output:** `selection.json` (primary pass).

Instructed to judge on fact body text. Tags are present in the context as metadata but the prompt states explicitly that tags are a hint, never a gate, and that an untagged fact relevant on its content must be selected (AC-R11.2).

```json
{
  "selected": [
    {"fact_id": "ey-ase2-rag", "requirement_ids": ["RQ1"], "strength": "strong",
     "reason": "Built classify→retrieve→generate pipeline on Azure AI Search in production",
     "depth": "expert"}
  ],
  "considered_and_rejected": [
    {"fact_id": "techgenstia-flutter", "reason": "Mobile UI work, no platform or ML relevance"}
  ]
}
```

`considered_and_rejected` is mandatory and is the audit trail: it proves the fact was read and judged rather than never seen. It is what makes a selection arguable by the user.

### 3.3 Recall

**Input:** `requirements.json` + **full corpus** + the Selector's `selected` ids (not its reasons). **Output:** `recall.json`.

An independent second pass with adversarial instructions: *find what the first pass missed*. It receives the Selector's picks but not its reasoning, so it cannot simply agree with an argument it has been handed.

Two jobs:

1. **Challenge omissions** — nominate facts the Selector dropped, with an argument.
2. **Flag tag gaps** — where a fact matched on content but its tags don't reflect that relevance, propose the missing tag (AC-R10.4). This is what makes tagging improve as a byproduct of normal use instead of being maintenance debt.

```json
{
  "additions": [
    {"fact_id": "xpar-ledger-acid", "requirement_ids": ["RQ4"],
     "argument": "JD asks for data integrity guarantees; this is ACID transaction design, tagged only 'fintech'"}
  ],
  "tag_proposals": [
    {"fact_id": "xpar-ledger-acid", "add_tags": ["data-integrity", "transactions"],
     "why": "content describes ACID guarantees but tags don't surface it"}
  ],
  "concurrences": ["ey-ase2-rag"]
}
```

**Disagreements are surfaced, not resolved** (AC-R12.2). The union of both passes goes forward; the review UI marks which facts only one pass chose. A machine silently arbitrating a recall dispute is exactly the silent omission the product exists to prevent.

### 3.4 Writer

**Input:** selected facts (full bodies) + `requirements.json` + `identity.yaml` + target length. **Output:** `draft.json`.

Constraints in the prompt:

- Every bullet cites the `fact_id`s it draws from.
- `depth` is a ceiling: an `exposure` fact may be mentioned, never framed as expertise (Q3).
- `locked_phrasing`, when set, is reproduced verbatim.
- Metrics are copied from the `metrics` field, never restated from the body prose — this prevents numeric drift.
- No claim may be introduced that isn't in a source fact.

```json
{
  "summary": "...",
  "sections": [
    {"kind": "experience", "role_id": "ey-ase2", "bullets": [
      {"text": "Architected end-to-end RAG pipelines...",
       "sources": ["ey-ase2-rag"], "metrics_used": ["50%"]}
    ]}
  ]
}
```

### 3.5 Validator

**Input:** `draft.json` + the full bodies of every cited fact. **Output:** `validation.json`.

Deliberately given no incentive to make the resume look good — its only job is grounding. Checks:

| Check | Action on failure |
|---|---|
| Every claim traces to a cited source fact | Cut the claim, report it |
| Every number appears in the source `metrics` | Cut or correct |
| Framing respects `depth` | Rewrite down, report |
| No `visibility: nda` content in body text | **Flag, report** — the renderer enforces (RK-7) |
| `locked_phrasing` reproduced exactly | Restore |
| Cited `fact_id`s exist | Flag as a pipeline bug |

```json
{
  "verdict": "changes_made",
  "cuts": [{"bullet": "...", "reason": "no source fact supports 'led a team of 5'"}],
  "warnings": [{"bullet": "...", "reason": "framed 'databricks' as expertise; depth is 'working'"}],
  "clean": true
}
```

Validator output is shown to the user, not hidden. A cut claim is informative — it often means a real fact is missing from the KB and should be added.

**The NDA check flags rather than cuts**, unlike every other row. The draft is shown to the user in review, and the user is entitled to see their own history there; the enforcement point is the renderer, which is the last gate before content leaves the machine ([spec-01 §3.3](spec-01-knowledge-base.md), [spec-05 §7](spec-05-latex-rendering.md)). A flagged bullet is marked in the review UI so the user knows it will not export as written.

## 4. Orchestration

```
Analyst
  └─▶ Selector  ─┐
      Recall    ─┴─▶ merge ─▶ Writer ─▶ Validator ─▶ review
```

Selector and Recall run **concurrently** — they are independent by construction, and running them in parallel halves wall-clock time on the most expensive stage. Everything else is sequential.

Each stage writes its artifact to `runs/<slug>/` before the next begins, so a failed run is resumable from the last completed stage rather than restarting from the JD.

### Chat revision loop

Post-generation chat (R5) re-enters the pipeline at the Writer with the conversation as additional instruction, then always re-runs the Validator. Chat can never bypass validation — otherwise "just add that I led the team" would write an unsupported claim straight into the document (AC-R5.2).

If a chat request needs a fact that doesn't exist, the response is a proposed KB entry (R13), not a resume edit.

## 5. Agent implementation

Each agent is a separate context with its own system prompt, invoked through the `RunnerBackend` ([spec-03](spec-03-runtime-auth.md)). On the SDK backend these map to `AgentDefinition` subagents; on the CLI backend each is a separate `claude -p` invocation with its own prompt file. The orchestrator code is identical in both cases — it sees only the backend interface.

Agents are given **no file-write tools**. They receive content as prompt input and return JSON. All disk writes go through the Python write path, which validates. An agent that could write `kb/` directly would bypass every guarantee in [spec-01](spec-01-knowledge-base.md) §4.

**The curator** is a sixth agent, outside the tailoring pipeline. It maintains the knowledge base from a conversation (AC-R13.2, [spec-04 §6.8](spec-04-api-and-ui.md)) and shares the pipeline's invariants: it reads the full corpus, has no write tools, and *proposes* rather than writes. It is not one of the five because it is not part of a tailoring run, so the "five agents, not ten" budget in §6 is untouched — it runs only when the person is talking to it.

Model assignment: Analyst and Writer benefit from the strongest model; Selector and Recall are comprehension-heavy and also warrant it; Validator is a checking task where a smaller, cheaper model is adequate and arguably better suited. Exact assignment is config, tuned after the spike measures real cost.

## 6. Cost control

- **Prompt caching** — the corpus is a stable prefix across the Selector and Recall calls and across runs in a session; the JD is the variable suffix. Ordering the prompt corpus-first is what makes caching effective.
- **Five agents, not ten.** Each agent is a full context against shared rate limits (RK-2). Additional agents must justify themselves against that budget.
- **Per-run token accounting** surfaced in the UI, so the user can see what a run costs before rate limits surprise them.
