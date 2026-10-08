"""An eval case: a posting and what a good selection of facts looks like.

`build_case` snapshots a finished run. The facts the run chose become
`must_include` — but they are the *model's* choice until a person has looked at
them, so a fresh case is marked `reviewed: false` and its scores mean "stays
consistent with that run", a regression signal, not "is correct". Editing the
JSON (add to `must_include`, move wrong picks to `must_exclude`, set `reviewed`)
is what turns it into a measure of quality.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..pipeline.artifacts import Run


@dataclass
class Case:
    id: str
    posting: str
    must_include: list[str]
    must_exclude: list[str] = field(default_factory=list)
    #: Everything the baseline run selected, for the stability score.
    baseline: list[str] = field(default_factory=list)
    reviewed: bool = False
    source_run: str | None = None
    #: Kept so the validator probe can run without regenerating a draft.
    baseline_draft: dict[str, Any] | None = None
    baseline_merged: dict[str, Any] | None = None
    notes: str = ""


def cases_dir(root: Path) -> Path:
    return Path(root) / "evals" / "cases"


def build_case(run: Run, name: str | None = None) -> Case:
    if not (run.has("posting") and run.has("merged")):
        raise ValueError(f"run {run.id} has no posting/selection yet; finish it first")
    merged = run.read("merged")
    posting = run.path("posting").read_text(encoding="utf-8")
    facts = merged["facts"]
    return Case(
        id=name or run.id,
        posting=posting,
        must_include=[
            f["fact_id"]
            for f in facts
            if f.get("strength") in ("strong", "moderate")
            and f.get("chosen_by") in ("both", "selector")
        ],
        baseline=[f["fact_id"] for f in facts],
        source_run=run.id,
        baseline_draft=run.read("draft") if run.has("draft") else None,
        baseline_merged=merged,
    )


def save_case(root: Path, case: Case) -> Path:
    directory = cases_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{case.id}.json"
    path.write_text(json.dumps(asdict(case), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_cases(root: Path, only: list[str] | None = None) -> list[Case]:
    directory = cases_dir(root)
    if not directory.is_dir():
        return []
    cases = [
        Case(**json.loads(p.read_text(encoding="utf-8"))) for p in sorted(directory.glob("*.json"))
    ]
    return [c for c in cases if not only or c.id in only]
