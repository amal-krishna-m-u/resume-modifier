# Spec 07 — Applications and Tracker

**Covers:** R17, R18, R19, R20
**Related:** [KB](spec-01-knowledge-base.md) · [API/UI](spec-04-api-and-ui.md) · [LaTeX](spec-05-latex-rendering.md) · [open-questions.md](open-questions.md) OQ-8

---

## 0. Fit — reuse before a new tailor

Most postings are a shape you have already written a resume for. Fit ranks completed runs and promoted applications against the new JD **on the machine, with no model call**, then shows the gaps that resume does not cover.

The person then:

1. **Uses that resume** as-is (open the run or the application record).
2. **Fills the gaps** — one Writer + Validator chat turn on the existing draft, told exactly which holes to cover. It must not invent facts.
3. **Runs the five-agent pipeline** when the posting is a new shape, or Fit's score is below the reuse floor (0.32 cosine on posting + resume text).

Fit is ranking among resumes that already exist. It does not filter the knowledge base (AC-R11.3). A local overlap of requirement-like lines is a sketch, not the Analyst; filling gaps is how implied requirements get a model pass without paying for Selector and Recall again.

---

## 1. Runs are not applications

A second boundary, parallel to the `kb/` vs `runs/` one in [spec-01 §1](spec-01-knowledge-base.md):

| | `runs/` | `applications/` |
|---|---|---|
| What | Tailoring attempts | What was actually sent |
| Count | Many per job description | One per submission |
| Lifetime | Disposable | Permanent |
| Mutability | Rewritten freely | Frozen on promotion |

**Promotion is explicit.** Exporting a PDF does not create an application record — you often export to look at something. The record is created when the user says "I applied," because that is the only moment the system can know the content became permanent.

### Why freezing matters

This is the whole point of the feature, not an implementation detail.

The knowledge base changes continuously: facts get rewritten, metrics sharpened, bullets re-worded. A resume *regenerated* from today's KB against a three-month-old job description is **not** the resume that was sent. Preparing for an interview against reconstructed content is worse than having no record, because it is confidently wrong — you walk in ready to discuss bullets the interviewer never read.

So an application stores the rendered artifacts *and* a content snapshot, hashed, and the system can prove neither has changed.

## 2. Archive layout

```
applications/
├── google/
│   ├── ml-engineer-R12345-2026-10-07/
│   │   ├── application.yaml          ← tracker record, source of truth
│   │   ├── posting.txt               ← the JD as applied against
│   │   ├── content-snapshot.json     ← frozen content, see §5
│   │   ├── resume-referral.pdf
│   │   ├── resume-referral.tex
│   │   ├── resume-direct.pdf
│   │   ├── resume-direct.tex
│   │   └── gap-report.md
│   └── backend-engineer-R98765-2026-11-02/
├── stripe/
│   └── platform-engineer-a3f9c1-2026-10-15/
└── _views/                           ← generated, gitignored, never read by code
    └── by-month/
        └── 2026-10/
            ├── google-ml-engineer     → ../../../google/ml-engineer-R12345-2026-10-07
            └── stripe-platform-eng    → ../../../stripe/platform-engineer-a3f9c1-2026-10-15
```

Company-first, because the lookup that matters is "what did I send to this company" — and a directory tree has exactly one primary axis. Month access comes from `_views/` and from the tracker UI, neither of which competes with the canonical structure.

Files are named `resume-referral` / `resume-direct` rather than `cv1` / `cv2`. Six months later, `cv1` requires remembering a convention; `referral` does not.

## 3. Slug algorithm

Folder names are permanent once written, so this is specified exactly.

**Company slug:** NFC-normalise → lowercase → non-alphanumeric runs to `-` → strip leading/trailing `-`. `Böhler & Co.` → `bohler-co`.

**Leaf name:** `<role-slug>-<discriminator>-<YYYY-MM-DD>`, where the discriminator is:
1. `job_id` slugified, when the posting provides one — stable and meaningful
2. otherwise, the first 6 hex characters of `sha256(job_url or posting_text)` — stable across re-runs of the same posting, which a random suffix would not be
3. on residual collision, append `-2`, `-3`

**Filesystem safety**, all mandatory:
- strip `/ \ : * ? " < > |` and control characters
- NFC-normalise, because macOS and Linux disagree on unicode decomposition
- lowercase throughout — **APFS is case-insensitive by default, so `Google/` and `google/` must not be allowed to become two folders holding half the history each**
- cap each path component at 255 bytes, truncating the role slug first and never the date or discriminator

The date is the **application date**, not the run date. A run prepared on Friday and submitted Monday files under Monday, because that is the date a recruiter will reference.

## 4. `application.yaml`

Source of truth for one application. Hand-editable, as everything in this project is.

```yaml
id: google/ml-engineer-R12345-2026-10-07
company: Google
role: ML Engineer
job_id: R12345
job_url: https://careers.google.com/jobs/results/R12345
source: referral            # referral | board | direct | recruiter | other
applied_on: 2026-10-07
status: screening           # see §4.1

contact_sets_rendered: [referral, direct]
contact_set_sent: referral  # which one actually went out; null until known

resumes:
  referral:
    pdf: resume-referral.pdf
    tex: resume-referral.tex
    sha256: 9f2c…
  direct:
    pdf: resume-direct.pdf
    tex: resume-direct.tex
    sha256: 4ab1…

referral:
  received: true
  referrer: Former EY colleague, platform team
  referred_on: 2026-10-06
  notes: Submitted through internal portal

run_id: 2026-10-06-google-ml-engineer
snapshot: content-snapshot.json
snapshot_sha256: c7e4…

stages:
  - {on: 2026-10-14, kind: screening_call, notes: "30 min, recruiter; asked about the trading engine latency work"}
  - {on: 2026-10-21, kind: technical, notes: "..."}

notes: |
  Freeform.
```

### 4.1 Status

`draft` → `applied` → `screening` → `interview` → `offer`, with `rejected`, `withdrawn`, and `ghosted` reachable from any state.

`ghosted` exists as a distinct terminal state because "no response after N weeks" is the most common real outcome and conflating it with `rejected` destroys the only signal you have about which application channels actually work.

### 4.2 What is mutable

| Frozen on promotion | Mutable forever |
|---|---|
| `posting.txt` | `status` |
| `content-snapshot.json` | `stages` |
| `resume-*.pdf` / `.tex` | `referral` block |
| `resumes.*.sha256` | `contact_set_sent` |
| `applied_on`, `company`, `role`, `job_id` | `notes` |

**What was sent** freezes. **What happened next** does not. Conflating the two would make the tracker useless for its primary job.

### 4.3 Enforcement

On promotion: artifacts are hashed, hashes written into `application.yaml`, and the artifact files set read-only (`0o444`).

`GET /api/applications/{id}/verify` re-hashes and reports drift. Read-only mode is a guardrail against accident, not a security boundary — anyone can `chmod` — so the hash is what actually establishes integrity.

## 5. `content-snapshot.json`

What makes R20 work. Captures not just the rendered bullets but the **source fact text as it read at send time**, so a later KB edit cannot silently rewrite history.

```json
{
  "frozen_at": "2026-10-07T09:14:22Z",
  "run_id": "2026-10-06-google-ml-engineer",
  "identity": {
    "name": "…",
    "contact_set": "referral",
    "contact": {"email": "…", "phone": "…"}
  },
  "template_version": "resume.tex.j2@a1b2c3d",
  "requirements": [{"id": "RQ1", "text": "Production RAG at scale", "kind": "required"}],
  "bullets": [
    {
      "section": "experience",
      "role_id": "ey-ase2",
      "text": "Architected end-to-end RAG pipelines…",
      "sources": ["ey-ase2-rag"],
      "requirement_ids": ["RQ1"]
    }
  ],
  "facts_as_sent": [
    {
      "id": "ey-ase2-rag",
      "sha256": "…",
      "body": "<full fact body text at freeze time>",
      "depth": "expert",
      "metrics": [{"value": "50%", "what": "reduction in manual triage time"}]
    }
  ],
  "gaps": [{"requirement_id": "RQ4", "status": "absent"}]
}
```

`facts_as_sent` embeds the full body text rather than referencing `kb/` by id. A reference would resolve to the *current* fact, which defeats the purpose. The duplication is intentional and cheap — a few KB per application.

`template_version` is recorded because layout affects what fits on the page, and therefore what the reader saw.

## 6. SQLite as a derived index

`.cache/applications.db`, built by scanning every `application.yaml`.

**It is a cache, not a database of record.** The same rules as `.cache/index.json` ([spec-01 §6](spec-01-knowledge-base.md)):

1. Deleting it is always safe; the next request rebuilds it.
2. Rebuilds are idempotent.
3. Nothing reads it as authority — detail views read the YAML.
4. Hand-edit a YAML, trigger a reindex, and the change appears. This is a **supported workflow**, not a workaround.
5. Staleness is detected by comparing file mtime against the indexed row; a stale row triggers a re-read of that file.

```sql
CREATE TABLE applications (
  id            TEXT PRIMARY KEY,   -- "google/ml-engineer-R12345-2026-10-07"
  company       TEXT NOT NULL,
  company_slug  TEXT NOT NULL,
  role          TEXT NOT NULL,
  job_id        TEXT,
  job_url       TEXT,
  source        TEXT,
  applied_on    TEXT NOT NULL,      -- ISO date, sorts lexicographically
  status        TEXT NOT NULL,
  referral_received INTEGER NOT NULL DEFAULT 0,
  referrer      TEXT,
  contact_set_sent  TEXT,
  run_id        TEXT,
  last_stage_on TEXT,
  yaml_mtime    REAL NOT NULL,
  yaml_path     TEXT NOT NULL
);
CREATE INDEX idx_company  ON applications(company_slug);
CREATE INDEX idx_status   ON applications(status);
CREATE INDEX idx_applied  ON applications(applied_on DESC);
CREATE INDEX idx_referral ON applications(referral_received);
```

### On data structures

No custom structures are needed, and this is a deliberate decision rather than an omission.

At 500 applications a year for five years — ~2,500 records of ~1KB — a full scan and parse is milliseconds, and SQLite's B-tree indexes over that are effectively instant. The indexes above *are* the data structure, implemented by someone else and reached through `CREATE INDEX`.

The real problems in this spec are immutability (§4.2), collision-free naming (§3), and filesystem portability (§3). Optimising lookup complexity here would be solving a problem that does not exist.

## 7. Generated views

`applications/_views/by-month/<YYYY-MM>/<company-slug>-<role-slug>` → relative symlink to the canonical directory.

Regenerated wholesale on reindex: the tree is deleted and rebuilt rather than patched, which makes it impossible for it to drift. Gitignored, never read by application code, and safe to delete. Relative symlinks so the archive survives being moved or synced.

## 8. Dual contact sets (R17)

`kb/identity.yaml` carries named sets; schema and validation in [spec-01 §2](spec-01-knowledge-base.md).

**Every run renders every configured set.** Two files, one pipeline execution — the tailored content is identical and only the contact block differs, so re-running the agents for the second variant would burn tokens to produce the same bullets.

The renderer takes a `contact_set` argument ([spec-05 §7](spec-05-latex-rendering.md)) and the export writes one file per set. With only one set configured, one file is produced and nothing else changes.

**Operational caution, recorded as [PRD](PRD.md) RK-8:** submitting twice to the same role under different contact details may trip ATS deduplication, or read as duplicate applying to a recruiter who sees both. The tracker's `contact_set_sent` field exists so the user knows which identity reached which company. This is a judgement call for the user, and the system records rather than polices it.

## 9. Lifecycle

```
run (runs/<slug>/)
  │  user: "I applied"
  ▼
POST /api/runs/{id}/promote   { company, role, job_id?, job_url?, applied_on, source }
  │
  ├─ resolve slug (§3), create applications/<company>/<leaf>/
  ├─ copy posting.txt, gap-report.md, resume-*.{pdf,tex}
  ├─ build content-snapshot.json from the run's selection + KB state (§5)
  ├─ hash everything, write application.yaml, chmod 0o444 on artifacts
  ├─ upsert the SQLite row, regenerate _views/
  └─ the run stays in runs/ and remains disposable
```

Promotion is **idempotent on the slug**: re-promoting the same run to the same slug is refused with a conflict naming the existing application, rather than silently creating `-2`. A true reapplication is a new run with a new date, which produces a different leaf name naturally.

## 10. Privacy

`applications/` is **gitignored**. It contains both contact sets, complete resumes, job descriptions, and third-party referrer names, and the repository is public. This resolves [open-questions.md](open-questions.md) OQ-3 for both `runs/` and `applications/`.

Durability comes from these being plain files in a backed-up home directory, not from version control. Referrer names are other people's information; they stay local.
