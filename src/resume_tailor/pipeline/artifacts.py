"""Run directories and stage artifacts (spec-02 §4).

Each stage writes its artifact to `runs/<slug>/` before the next begins, so a
failed run resumes from the last completed stage rather than restarting from
the job description. With the Selector and Recall each reading the full corpus,
restarting a five-stage run because the Writer timed out would re-spend the two
most expensive calls for nothing.

`runs/` is disposable and gitignored (OQ-3). Nothing here is a source of truth:
everything is reproducible from `kb/` plus the posting.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

#: Stage name -> filename. Stage order is the pipeline order.
ARTIFACTS = {
    "meta": "meta.json",
    "posting": "posting.txt",
    "requirements": "requirements.json",
    "selection": "selection.json",
    "recall": "recall.json",
    "merged": "merged.json",
    "draft": "draft.json",
    "draft-previous": "draft-previous.json",
    "chat": "chat.jsonl",
    "validation": "validation.json",
    "gaps": "gaps.json",
    "usage": "usage.json",
}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_length: int = 48) -> str:
    """Lowercase ASCII slug. Lowercase is not cosmetic — APFS is
    case-insensitive, so `Acme` and `acme` must not become two directories."""
    normalised = unicodedata.normalize("NFKD", text)
    ascii_only = normalised.encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP.sub("-", ascii_only.lower()).strip("-")
    return slug[:max_length].strip("-") or "run"


_LABEL = re.compile(r"^\s*(?:job\s*title|title|role|position|opening|vacancy)\s*[:\-–—]\s*", re.I)


def guess_role(posting: str) -> str | None:
    """A job title from the top of a pasted posting.

    Postings nearly always open with the title, so the first reasonably short
    line is right far more often than not. It only has to be good enough to
    name a folder and to label the run until the Analyst reads the posting
    properly — the Analyst's `role_title` takes over as the display name.
    """
    for line in posting.splitlines()[:12]:
        line = _LABEL.sub("", line.strip().lstrip("#*-•> ").rstrip("*#: "))
        if 3 <= len(line) <= 90 and not line.lower().startswith(("http", "about ", "overview")):
            return line
    return None


def run_slug(role: str | None, company: str | None = None, on: date | None = None) -> str:
    """`<date>-<company>-<role>`, leaving out whatever is not known.

    This used to fall back to the literal word "untitled" for a missing role,
    which showed up in every run the web form created — it only sent the
    posting and a company, never a role.
    """
    parts = [(on or date.today()).isoformat()]
    if company:
        parts.append(slugify(company, max_length=24))
    if role:
        parts.append(slugify(role, max_length=36))
    if len(parts) == 1:
        parts.append("posting")
    return "-".join(parts)


def humanise_id(run_id: str) -> str:
    """`2026-10-07-visa-untitled` -> `Visa`. The last resort, for a run with
    nothing else to call it."""
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", run_id)
    stem = re.sub(r"-(untitled|posting)(-\d+)?$", "", stem)
    stem = re.sub(r"-\d+$", "", stem)
    return stem.replace("-", " ").strip().title() or run_id


@dataclass
class Run:
    """One tailoring attempt on disk."""

    directory: Path

    @property
    def id(self) -> str:
        return self.directory.name

    @classmethod
    def create(cls, runs_dir: Path, slug: str) -> Run:
        """Make a fresh run directory, suffixing on collision.

        Never reuses a directory: a second attempt at the same posting on the
        same day is a separate run, and silently overwriting the first would
        destroy the comparison that makes a re-run worth doing.
        """
        directory = runs_dir / slug
        suffix = 2
        while directory.exists():
            directory = runs_dir / f"{slug}-{suffix}"
            suffix += 1
        directory.mkdir(parents=True)
        return cls(directory)

    def path(self, stage: str) -> Path:
        try:
            return self.directory / ARTIFACTS[stage]
        except KeyError:
            known = ", ".join(ARTIFACTS)
            raise ValueError(f"unknown stage {stage!r}; expected one of: {known}") from None

    def has(self, stage: str) -> bool:
        path = self.path(stage)
        return path.is_file() and path.stat().st_size > 0

    def write(self, stage: str, data: Any) -> Path:
        """Write atomically, so an interrupted run cannot leave a truncated
        artifact that the resume path then reads as complete."""
        path = self.path(stage)
        text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return path

    def read(self, stage: str) -> Any:
        path = self.path(stage)
        text = path.read_text(encoding="utf-8")
        return text if path.suffix == ".txt" else json.loads(text)

    def meta(self) -> dict[str, Any]:
        """What the person told us about this run (company, a title they chose)."""
        if not self.has("meta"):
            return {}
        try:
            data = self.read("meta")
        except (ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def title(self) -> str:
        """What to call this run when showing it to a person.

        In order of authority: a title they set themselves, the role the
        Analyst read out of the posting, the first line of the posting, and
        only then the folder name made readable. The folder name is permanent
        and was never meant to be the label.
        """
        chosen = self.meta().get("title")
        if isinstance(chosen, str) and chosen.strip():
            return chosen.strip()

        if self.has("requirements"):
            try:
                role = self.read("requirements").get("role_title")
            except (ValueError, OSError, AttributeError):
                role = None
            if isinstance(role, str) and role.strip():
                return role.strip()

        if self.has("posting"):
            guessed = guess_role(self.read("posting"))
            if guessed:
                return guessed

        return humanise_id(self.id)

    def company(self) -> str | None:
        value = self.meta().get("company")
        return value.strip() if isinstance(value, str) and value.strip() else None

    def completed_stages(self) -> list[str]:
        return [stage for stage in ARTIFACTS if self.has(stage)]


def list_runs(runs_dir: Path) -> list[Run]:
    """Newest first, by directory name — which sorts correctly because the
    slug leads with an ISO date."""
    if not runs_dir.is_dir():
        return []
    return [Run(p) for p in sorted(runs_dir.iterdir(), reverse=True) if p.is_dir()]
