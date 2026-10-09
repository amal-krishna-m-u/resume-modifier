"""Fit a new posting to a resume already on disk — no model, no tokens.

The five-agent pipeline is for a *new shape* of job. Most postings are a shape
you have already written for. Spending five full-corpus calls to rediscover
that is the expensive failure mode at volume.

Fit ranks completed runs and promoted applications by how close their posting
(and the resume text that came out of it) is to the new JD. Gaps are a local
overlap of requirement-like lines against that resume. The person then reuses
it, asks chat to fill only the holes, or runs the pipeline for a genuinely
new shape.

This is ranking, not selection. Nothing here drops a fact from the knowledge
base (AC-R11.3); it only chooses among resumes that already exist.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..applications import db as appdb
from ..pipeline.artifacts import Run, list_runs

Kind = Literal["run", "application"]

#: Below this, Fit still lists neighbours but does not recommend reuse.
REUSE_FLOOR = 0.32

_TOKEN = re.compile(r"[a-z][a-z0-9+#.]{1,}")
_BULLET = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
_MUST = re.compile(
    r"\b(must|required|need to|experience (?:with|in)|proficien\w+|responsib|"
    r"familiar with|knowledge of|skills?:)\b",
    re.I,
)
_STOP = frozenset(
    """
    a an the and or of to for in on at by with from as is are was were be been
    this that these those it its you your we our they their will would should
    can may about into over such than then them also more most other any all
    not no yes job role team work working using used use including include
    strong good well ability able years year experience requirements
    responsibilities description posting company
    """.split()  # noqa: SIM905
)


@dataclass
class ResumeCard:
    kind: Kind
    id: str
    title: str
    company: str | None
    run_id: str | None
    posting: str
    resume_text: str
    role_title: str | None = None


@dataclass
class Gap:
    text: str
    status: Literal["absent", "weak", "covered"]
    overlap: float


@dataclass
class Fit:
    card: ResumeCard
    score: float
    posting_score: float
    resume_score: float
    gaps: list[Gap] = field(default_factory=list)
    recommend: bool = False

    @property
    def absent(self) -> list[Gap]:
        return [g for g in self.gaps if g.status == "absent"]

    @property
    def weak(self) -> list[Gap]:
        return [g for g in self.gaps if g.status == "weak"]


def tokens(text: str) -> list[str]:
    return [w for w in _TOKEN.findall(text.lower()) if w not in _STOP]


def tf(words: list[str]) -> dict[str, float]:
    counts = Counter(words)
    n = sum(counts.values()) or 1
    return {k: v / n for k, v in counts.items()}


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    num = sum(left[k] * right[k] for k in shared)
    den = math.sqrt(sum(v * v for v in left.values())) * math.sqrt(
        sum(v * v for v in right.values())
    )
    return num / den if den else 0.0


def flatten_draft(draft: dict[str, Any]) -> str:
    parts: list[str] = []
    if isinstance(draft.get("summary"), str):
        parts.append(draft["summary"])
    for section in draft.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for bullet in section.get("bullets") or []:
            if isinstance(bullet, dict):
                lead = bullet.get("lead") or ""
                text = bullet.get("text") or ""
                parts.append(f"{lead} {text}".strip())
            elif isinstance(bullet, str):
                parts.append(bullet)
        for skill in section.get("items") or []:
            if isinstance(skill, str):
                parts.append(skill)
            elif isinstance(skill, dict) and skill.get("name"):
                parts.append(str(skill["name"]))
    return "\n".join(parts)


def flatten_requirements(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    if isinstance(payload.get("role_title"), str):
        parts.append(payload["role_title"])
    for item in payload.get("requirements") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("text") or ""))
            parts.append(str(item.get("quote") or ""))
        elif isinstance(item, str):
            parts.append(item)
    return "\n".join(p for p in parts if p)


def cues(posting: str) -> list[str]:
    """Requirement-shaped lines from a posting. Local, lossy, and enough to
    tell the person what this JD asks that the existing resume does not say.

    Soft-wrapped sentences are joined first, because a 'Required:' line that
    continues on the next line is one requirement, not two fragments.
    """
    found: list[str] = []
    collapsed = re.sub(r"\s+", " ", posting)
    for sentence in re.split(r"(?<=[.!;])\s+", collapsed):
        line = sentence.strip().lstrip("#").strip()
        if not (24 <= len(line) <= 280):
            continue
        if _BULLET.match(line) or _MUST.search(line):
            found.append(_BULLET.sub("", line))
    for raw in posting.splitlines():
        line = raw.strip().lstrip("#").strip()
        if not (24 <= len(line) <= 240):
            continue
        if _BULLET.match(line):
            found.append(_BULLET.sub("", line))
    return list(dict.fromkeys(found))[:40]


def gap_status(cue: str, resume: dict[str, float]) -> Gap:
    words = tokens(cue)
    if not words:
        return Gap(cue, "weak", 0.0)
    hits = sum(1 for w in words if w in resume)
    overlap = hits / len(words)
    if overlap >= 0.45:
        status: Literal["absent", "weak", "covered"] = "covered"
    elif overlap >= 0.22:
        status = "weak"
    else:
        status = "absent"
    return Gap(cue, status, round(overlap, 3))


def score_card(posting: str, card: ResumeCard) -> Fit:
    posting_tf = tf(tokens(posting))
    posting_score = cosine(posting_tf, tf(tokens(card.posting)))
    resume_score = cosine(posting_tf, tf(tokens(card.resume_text)))
    score = 0.7 * posting_score + 0.3 * resume_score
    role = (card.role_title or "").lower().strip()
    guessed = tokens(posting)[:12]
    if role and any(w in role for w in guessed if len(w) > 3):
        score = min(1.0, score + 0.05)
    resume_tf = tf(tokens(card.resume_text))
    gaps = [gap_status(cue, resume_tf) for cue in cues(posting)]
    return Fit(
        card=card,
        score=round(score, 4),
        posting_score=round(posting_score, 4),
        resume_score=round(resume_score, 4),
        gaps=gaps,
        recommend=score >= REUSE_FLOOR,
    )


def _run_card(run: Run) -> ResumeCard | None:
    if not (run.has("posting") and run.has("draft") and run.has("validation")):
        return None
    try:
        posting = run.read("posting")
        draft = run.read("draft")
    except (ValueError, OSError):
        return None
    if not isinstance(posting, str) or not isinstance(draft, dict):
        return None
    role = None
    extra = ""
    if run.has("requirements"):
        try:
            req = run.read("requirements")
        except (ValueError, OSError):
            req = {}
        if isinstance(req, dict):
            role = req.get("role_title") if isinstance(req.get("role_title"), str) else None
            extra = flatten_requirements(req)
    return ResumeCard(
        kind="run",
        id=run.id,
        title=run.title(),
        company=run.company(),
        run_id=run.id,
        posting=posting,
        resume_text=f"{flatten_draft(draft)}\n{extra}",
        role_title=role,
    )


def _application_card(path: Path, application: Any) -> ResumeCard | None:
    folder = path.parent
    posting_path = folder / "posting.txt"
    if not posting_path.is_file():
        return None
    posting = posting_path.read_text(encoding="utf-8")
    resume_parts: list[str] = []
    snapshot_path = folder / "content-snapshot.json"
    if snapshot_path.is_file():
        try:
            snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            snap = {}
        if isinstance(snap, dict):
            draft = {
                "summary": snap.get("summary"),
                "sections": [{"bullets": snap.get("bullets") or []}],
            }
            resume_parts.append(flatten_draft(draft))
            if isinstance(snap.get("requirements"), dict):
                resume_parts.append(flatten_requirements(snap["requirements"]))
    report = folder / "gap-report.md"
    if report.is_file() and not resume_parts:
        resume_parts.append(report.read_text(encoding="utf-8")[:4000])
    if not resume_parts:
        resume_parts.append(posting)
    return ResumeCard(
        kind="application",
        id=application.id,
        title=application.role,
        company=application.company,
        run_id=application.run_id,
        posting=posting,
        resume_text="\n".join(resume_parts),
        role_title=application.role,
    )


def library(runs_dir: Path, applications_dir: Path) -> list[ResumeCard]:
    cards: list[ResumeCard] = []
    seen_runs: set[str] = set()
    for path, application in appdb.scan(applications_dir):
        card = _application_card(path, application)
        if card is None:
            continue
        cards.append(card)
        if card.run_id:
            seen_runs.add(card.run_id)
    for run in list_runs(runs_dir):
        if run.id in seen_runs:
            continue
        card = _run_card(run)
        if card is not None:
            cards.append(card)
    return cards


def fit_run(posting: str, run: Run) -> Fit | None:
    card = _run_card(run)
    if card is None:
        return None
    return score_card(posting, card)


def fit(
    posting: str,
    runs_dir: Path,
    applications_dir: Path,
    *,
    limit: int = 3,
) -> list[Fit]:
    posting = posting.strip()
    if not posting:
        return []
    ranked = sorted(
        (score_card(posting, card) for card in library(runs_dir, applications_dir)),
        key=lambda row: row.score,
        reverse=True,
    )
    return ranked[:limit]


def fill_prompt(posting: str, result: Fit) -> str:
    """A chat turn that asks the Writer to cover Fit's gaps on the existing draft."""
    holes = result.absent + result.weak
    lines = [
        "This is a new posting that is close to the resume already in this run.",
        "Update the draft so it covers the gaps below. Do not invent facts.",
        "If a gap is not supported by a recorded fact, leave it as a gap.",
        "",
        "Gaps to cover:",
    ]
    if not holes:
        lines.append("- No local gaps; retarget wording to the new posting.")
    for gap in holes:
        lines.append(f"- ({gap.status}) {gap.text}")
    excerpt = posting.strip()
    if len(excerpt) > 2500:
        excerpt = excerpt[:2500] + "\n…"
    lines += ["", "New posting:", excerpt]
    return "\n".join(lines)


def as_json(result: Fit) -> dict[str, Any]:
    card = result.card
    return {
        "kind": card.kind,
        "id": card.id,
        "title": card.title,
        "company": card.company,
        "run_id": card.run_id,
        "role_title": card.role_title,
        "score": result.score,
        "posting_score": result.posting_score,
        "resume_score": result.resume_score,
        "recommend": result.recommend,
        "covered": sum(1 for g in result.gaps if g.status == "covered"),
        "weak": [{"text": g.text, "overlap": g.overlap} for g in result.weak],
        "absent": [{"text": g.text, "overlap": g.overlap} for g in result.absent],
    }
