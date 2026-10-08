"""`.cache/index.json` — the derived index (spec-01 §6).

**This is not a retrieval surface.** No agent selects from it. It exists for UI
list rendering and corpus statistics, and nothing else.

That warning is here rather than in a design document because this index is
exactly the thing that would tempt a future implementer back into filtering the
corpus before a model reads it — the silent omission R11 forbids. Selection
reads full fact bodies, always (spec-02 §2).

Deleting this file is always safe; the next request rebuilds it.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .loader import Corpus

INDEX_VERSION = 3


@dataclass(frozen=True)
class IndexRow:
    id: str
    type: str
    title: str
    tags: list[str]
    parent: str | None
    depth: str
    visibility: str
    verifiable: bool
    dates: dict[str, str] | None
    metrics: int
    estimated_tokens: int
    #: Words of real body text, excluding bootstrap TODO comments. The UI uses
    #: this to show which entries are too thin to carry a claim — every
    #: "matched, but not strongly" row in a gap report is a thin body, and
    #: finding it should not require opening each entry.
    body_words: int
    path: str
    sha256: str
    mtime: float


def build_index(corpus: Corpus) -> dict:
    rows: list[IndexRow] = []
    for entry in corpus.entries:
        dates = getattr(entry.meta, "dates", None)
        rows.append(
            IndexRow(
                id=entry.id,
                type=entry.type,
                title=entry.meta.title,
                tags=list(entry.meta.tags),
                parent=getattr(entry.meta, "parent", None),
                depth=entry.meta.depth,
                visibility=entry.meta.visibility,
                verifiable=entry.meta.verifiable,
                dates=dates.model_dump(exclude_none=True) if dates else None,
                metrics=len(entry.meta.metrics),
                estimated_tokens=entry.estimated_tokens(),
                body_words=len(entry.body.split("<!--")[0].split()),
                path=str(entry.path.relative_to(corpus.root)),
                sha256=entry.sha256,
                mtime=entry.path.stat().st_mtime,
            )
        )

    return {
        "version": INDEX_VERSION,
        "derived": True,
        "note": "Rebuildable cache. Not authoritative. Not a retrieval surface (spec-01 §6).",
        "counts": {t: len(corpus.of_type(t)) for t in sorted({e.type for e in corpus.entries})},
        "estimated_corpus_tokens": corpus.estimated_tokens(),
        "taxonomy_terms": len(corpus.taxonomy),
        "skills": len(corpus.skills),
        "entries": [asdict(r) for r in rows],
    }


def write_index(corpus: Corpus, cache_dir: Path) -> Path:
    """Write the index atomically.

    Atomic even though it is only a cache: a half-written index read by a
    concurrent request raises a JSON error that looks like corruption, and
    chasing that is time spent on a file that was never authoritative.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / "index.json"
    tmp = cache_dir / "index.json.tmp"
    tmp.write_text(json.dumps(build_index(corpus), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def invalidate(cache_dir: Path) -> None:
    """Drop the index. Called after any write to `kb/` (spec-04 §2 step 7)."""
    (cache_dir / "index.json").unlink(missing_ok=True)
