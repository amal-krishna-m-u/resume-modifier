"""Run the cases against the current prompts and model; compare two runs.

Two measurements per case, chosen because they are the two ways this product
fails:

* **Selection** — re-run Analyst, Selector and Recall on the posting. Scores:
  `recall` (share of `must_include` found), `exclusions` (picks the case says
  are wrong) and `stability` (F1 against everything the baseline chose).
* **Validator probe** — the Validator degrades *invisibly* (spec-06 §6), so it
  gets its own test: a plausible fabricated bullet ("Led a team of 12…") is
  added to the baseline draft, citing a real fact that does not support it. A
  Validator that does not cut or flag it is the failure that surfaces in an
  interview.

Each result records the prompt version (content hash) of every agent, the
backend and model, so a diff between two results is attributable.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..agents.specs import build_all
from ..config import Config
from ..observability import prompt_version, scope
from ..pipeline.artifacts import Run
from ..pipeline.corpus import Corpus
from ..pipeline.orchestrator import Pipeline
from ..runtime.base import RunnerBackend
from .cases import Case

FABRICATION = "Led a team of 12 engineers and cut infrastructure costs by 40% across three regions."


def results_dir(root: Path) -> Path:
    return Path(root) / "evals" / "results"


def inject(draft: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """A copy of `draft` with one unsupported bullet, citing a real fact."""
    draft = copy.deepcopy(draft)
    for section in draft.get("sections", []):
        if section.get("kind") == "experience" and section.get("bullets"):
            cited = section["bullets"][0].get("sources") or []
            section["bullets"].append(
                {
                    "lead": "Team Leadership",
                    "text": FABRICATION,
                    "sources": cited[:1],
                    "metrics_used": ["40%", "12"],
                }
            )
            return draft, FABRICATION
    raise ValueError("draft has no experience bullets to inject into")


def caught(validation: dict[str, Any], text: str) -> bool:
    """Whether the Validator cut or flagged `text`.

    It may quote the bullet whole, truncated, or with the lead-in attached, so
    the match is a containment either way, above a minimum length that stops a
    stray word from counting as a catch.
    """
    target = " ".join(text.lower().split())
    for key in ("cuts", "warnings"):
        for item in validation.get(key) or []:
            quoted = " ".join(str(item.get("bullet", "")).lower().split())
            if len(quoted) >= 20 and (quoted in target or target[:40] in quoted):
                return True
    return False


def score_selection(case: Case, got: list[str]) -> dict[str, float]:
    chosen, gold, base = set(got), set(case.must_include), set(case.baseline)
    hit = len(chosen & gold)
    inter = len(chosen & base)
    precision = inter / len(chosen) if chosen else 0.0
    recall_base = inter / len(base) if base else 0.0
    f1 = (2 * precision * recall_base / (precision + recall_base)) if inter else 0.0
    return {
        "recall": hit / len(gold) if gold else 1.0,
        "exclusions": float(len(chosen & set(case.must_exclude))),
        "stability": round(f1, 3),
    }


async def run_eval(
    root: Path,
    backend: RunnerBackend,
    corpus: Corpus,
    config: Config,
    cases: list[Case],
    *,
    label: str,
    probe_validator: bool = True,
    sink: Any = None,
) -> dict[str, Any]:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    work = Path(root) / "evals" / "runs" / f"{stamp}-{label}"
    agents = build_all(config.models)
    result: dict[str, Any] = {
        "label": label,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "backend": backend.name,
        "models": {n: a.model for n, a in agents.items()},
        "prompt_versions": {n: prompt_version(a.system_prompt) for n, a in agents.items()},
        "reviewed_cases": sum(c.reviewed for c in cases),
        "cases": {},
    }

    for case in cases:
        seed = f"eval:{stamp}-{label}:{case.id}"
        row: dict[str, Any] = {"reviewed": case.reviewed}
        with scope(run_id=seed, kind="eval", label=label):
            pipeline = Pipeline(backend, corpus, config, trace_extra={"label": label})
            run = Run.create(work, case.id)
            requirements = await pipeline.analyse(run, case.posting)
            selection = await pipeline.select_concurrent(run, requirements)
            row["selected"] = selection.fact_ids
            row["missed"] = sorted(set(case.must_include) - set(selection.fact_ids))
            row["scores"] = score_selection(case, selection.fact_ids)

            if probe_validator and case.baseline_draft and case.baseline_merged:
                probe = Run.create(work, f"{case.id}-probe")
                probe.write("merged", case.baseline_merged)
                baseline_selection = await pipeline.select(probe, requirements)
                bad, text = inject(case.baseline_draft)
                validation = await pipeline.validate(probe, bad, baseline_selection)
                row["scores"]["validator_catches_fabrication"] = float(caught(validation, text))
            row["usage"] = vars(pipeline.usage)

        if sink is not None:
            for name, value in row["scores"].items():
                sink.score(seed, name, value, comment=f"{label} / {case.id}")
        result["cases"][case.id] = row

    scores = [r["scores"] for r in result["cases"].values()]
    result["mean"] = {
        k: round(sum(s[k] for s in scores if k in s) / max(1, sum(k in s for s in scores)), 3)
        for k in {k for s in scores for k in s}
    }
    out = results_dir(root)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stamp}-{label}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result["file"] = f"{stamp}-{label}.json"
    if sink is not None:
        sink.flush()
    return result


def load_result(root: Path, name: str) -> dict[str, Any]:
    directory = results_dir(root)
    matches = sorted(directory.glob(f"*{name}*.json"))
    if not matches:
        raise FileNotFoundError(f"no eval result matching {name!r} in {directory}")
    return json.loads(matches[-1].read_text(encoding="utf-8"))


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """What changed between two results, and what could explain it."""
    changed = {
        agent: (a["prompt_versions"].get(agent), b["prompt_versions"].get(agent))
        for agent in b["prompt_versions"]
        if a["prompt_versions"].get(agent) != b["prompt_versions"].get(agent)
    }
    deltas = {
        k: round(b["mean"].get(k, 0) - a["mean"].get(k, 0), 3)
        for k in set(a["mean"]) | set(b["mean"])
    }
    return {
        "a": a["label"],
        "b": b["label"],
        "prompt_changes": changed,
        "backend_changed": (a["backend"], b["backend"]) if a["backend"] != b["backend"] else None,
        "models_changed": a["models"] != b["models"],
        "mean_a": a["mean"],
        "mean_b": b["mean"],
        "delta": deltas,
    }
