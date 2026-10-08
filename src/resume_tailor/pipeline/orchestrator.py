"""The five-agent run (spec-02 §4).

    Analyst
      └─▶ Selector  ─┐
          Recall    ─┴─▶ merge ─▶ Writer ─▶ Validator ─▶ review

Selector and Recall run **concurrently**. They are independent by construction
— Recall is given the Selector's picks but not its reasoning — and they are the
two most expensive calls in the run, so overlapping them roughly halves
wall-clock time on the stage that dominates it.

Every stage writes its artifact before the next begins, so a failure is
resumable rather than a restart.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..agents.specs import build_all
from ..config import Config
from ..kb.loader import Corpus
from ..runtime.base import AgentSpec, RunnerBackend, Usage
from .artifacts import Run
from .changes import draft_changes, summarise
from .corpus import estimate_tokens, render_corpus, render_selected
from .merge import SelectedFact, Selection, gap_report, merge

#: Stage lifecycle events, for the CLI and later for SSE (spec-04 §4).
Progress = Callable[[str, str, dict[str, Any]], None]


def _noop(stage: str, status: str, detail: dict[str, Any]) -> None:  # noqa: ARG001
    return None


@dataclass
class RunResult:
    run: Run
    requirements: dict[str, Any]
    selection: Selection
    draft: dict[str, Any]
    validation: dict[str, Any]
    gaps: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    per_agent: dict[str, Usage] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return bool(self.validation.get("clean"))


class Pipeline:
    def __init__(
        self,
        backend: RunnerBackend,
        corpus: Corpus,
        config: Config | None = None,
        *,
        on_progress: Progress | None = None,
    ) -> None:
        self.backend = backend
        self.corpus = corpus
        self.config = config or Config()
        self.agents = build_all(self.config.models)
        self.on_progress = on_progress or _noop
        self.usage = Usage()
        self.per_agent: dict[str, Usage] = {}

    # -- plumbing ----------------------------------------------------------

    async def _call(self, name: str, prompt: str, *, cache_prefix: str | None = None) -> Any:
        spec: AgentSpec = self.agents[name]
        self.on_progress(name, "running", {})

        result = await self.backend.run_agent(spec, prompt, cache_prefix=cache_prefix)

        self.usage = self.usage + result.usage
        self.per_agent[name] = result.usage
        self.on_progress(
            name,
            "done",
            {
                "input": result.usage.input_tokens,
                "output": result.usage.output_tokens,
                "cached": result.usage.cache_read_tokens,
                "repairs": result.repairs,
            },
        )
        return result.json

    def _corpus_text(self) -> str:
        return render_corpus(self.corpus)

    def check_context(self) -> None:
        """Refuse before spending anything if the corpus cannot fit.

        Checked once, up front. Discovering it on the Selector call would mean
        the Analyst's tokens were already spent on a run that cannot complete.
        """
        self.backend.capabilities.assert_corpus_fits(
            self.backend.name, estimate_tokens(self._corpus_text())
        )

    # -- stages ------------------------------------------------------------

    async def analyse(self, run: Run, posting: str) -> dict[str, Any]:
        if run.has("requirements"):
            self.on_progress("analyst", "skipped", {"reason": "already complete"})
            return run.read("requirements")
        requirements = await self._call("analyst", f"# JOB POSTING\n\n{posting}")
        run.write("requirements", requirements)
        return requirements

    async def select(self, run: Run, requirements: dict[str, Any]) -> Selection:
        if run.has("merged"):
            self.on_progress("selector", "skipped", {"reason": "already complete"})
            merged = run.read("merged")
            return merge(
                {
                    "selected": [
                        {**f, "fact_id": f["fact_id"]}
                        for f in merged["facts"]
                        if f["chosen_by"] in ("both", "selector")
                    ],
                    "considered_and_rejected": merged["considered_and_rejected"],
                },
                {
                    "additions": [f for f in merged["facts"] if f["chosen_by"] == "recall"],
                    "concurrences": [
                        f["fact_id"] for f in merged["facts"] if f["chosen_by"] == "both"
                    ],
                    "tag_proposals": merged.get("tag_proposals", []),
                },
                known_ids=set(self.corpus.by_id()),
            )

        corpus_text = self._corpus_text()
        requirements_text = _requirements_block(requirements)

        # Corpus first, posting last. The corpus is the stable prefix across
        # both calls and across runs in a session, which is what makes caching
        # effective (spec-03 §6).
        selector_prompt = f"{requirements_text}\n\nSelect the relevant facts."

        selection = await self._call("selector", selector_prompt, cache_prefix=corpus_text)
        run.write("selection", selection)

        # Recall sees WHICH facts were chosen, never WHY. Handed the argument
        # it would mostly agree with it, and a second pass that agrees is worth
        # nothing (spec-02 §3.3).
        chosen = [row.get("fact_id") for row in (selection.get("selected") or [])]
        recall_prompt = (
            f"{requirements_text}\n\n"
            "## Already selected by the first pass\n\n"
            + ("\n".join(f"- {fid}" for fid in chosen if fid) or "(nothing)")
            + "\n\nFind what it missed."
        )
        recall = await self._call("recall", recall_prompt, cache_prefix=corpus_text)
        run.write("recall", recall)

        merged = merge(selection, recall, known_ids=set(self.corpus.by_id()))
        run.write("merged", merged.to_dict())
        return merged

    async def select_concurrent(self, run: Run, requirements: dict[str, Any]) -> Selection:
        """Selector and Recall in parallel.

        Recall is given the Selector's picks when they are available, and runs
        blind when they are not. Running blind costs a little recall quality
        and buys back the whole of the Selector's latency; the orchestrator
        chooses sequencing, and the agents work either way.
        """
        if run.has("merged"):
            return await self.select(run, requirements)

        corpus_text = self._corpus_text()
        requirements_text = _requirements_block(requirements)

        selector_task = asyncio.create_task(
            self._call(
                "selector",
                f"{requirements_text}\n\nSelect the relevant facts.",
                cache_prefix=corpus_text,
            )
        )
        recall_task = asyncio.create_task(
            self._call(
                "recall",
                f"{requirements_text}\n\n"
                "## Already selected by the first pass\n\n"
                "(running concurrently — the first pass's picks are not yet available, "
                "so judge the corpus independently and nominate everything you would "
                "expect a careful reader to select)\n\nFind what matters.",
                cache_prefix=corpus_text,
            )
        )

        selection, recall = await asyncio.gather(selector_task, recall_task)
        run.write("selection", selection)
        run.write("recall", recall)

        merged = merge(selection, recall, known_ids=set(self.corpus.by_id()))
        run.write("merged", merged.to_dict())
        return merged

    async def write(
        self, run: Run, requirements: dict[str, Any], selection: Selection, *, bullets: int
    ) -> dict[str, Any]:
        if run.has("draft"):
            self.on_progress("writer", "skipped", {"reason": "already complete"})
            return run.read("draft")

        prompt = (
            f"{_requirements_block(requirements)}\n\n"
            f"{_selection_block(selection)}\n\n"
            f"Bullet budget: about {bullets} bullets in total across all roles.\n\n"
            "Write the resume."
        )
        draft = await self._call(
            "writer", prompt, cache_prefix=render_selected(self.corpus, selection.fact_ids)
        )
        run.write("draft", draft)
        return draft

    async def validate(
        self, run: Run, draft: dict[str, Any], selection: Selection, *, force: bool = False
    ) -> dict:
        """Always runs, including after a chat revision (AC-R5.2).

        Chat can never bypass validation, or "just add that I led the team"
        writes an unsupported claim straight into the document.
        """
        if run.has("validation") and not force:
            self.on_progress("validator", "skipped", {"reason": "already complete"})
            return run.read("validation")

        import json

        prompt = (
            "# DRAFT TO CHECK\n\n"
            f"{json.dumps(draft, indent=2, ensure_ascii=False)}\n\n"
            "Check it against the facts above."
        )
        validation = await self._call(
            "validator", prompt, cache_prefix=render_selected(self.corpus, selection.fact_ids)
        )
        run.write("validation", validation)
        return validation

    # -- the run -----------------------------------------------------------

    async def run(
        self,
        run: Run,
        posting: str,
        *,
        bullets: int = 9,
        concurrent: bool = True,
    ) -> RunResult:
        self.check_context()
        if not run.has("posting"):
            run.write("posting", posting)

        requirements = await self.analyse(run, posting)
        selection = (
            await self.select_concurrent(run, requirements)
            if concurrent
            else await self.select(run, requirements)
        )
        draft = await self.write(run, requirements, selection, bullets=bullets)
        validation = await self.validate(run, draft, selection)

        gaps = gap_report(requirements, selection)
        run.write("gaps", gaps)
        run.write(
            "usage",
            {
                "total": vars(self.usage),
                "per_agent": {name: vars(u) for name, u in self.per_agent.items()},
            },
        )

        return RunResult(
            run=run,
            requirements=requirements,
            selection=selection,
            draft=draft,
            validation=validation,
            gaps=gaps,
            usage=self.usage,
            per_agent=self.per_agent,
        )

    async def revise(
        self,
        run: Run,
        instruction: str,
        *,
        bullets: int = 9,
        already_recorded: bool = False,
    ) -> RunResult:
        """Re-enter at the Writer with a chat instruction (R5, spec-02 §4).

        **Always re-runs the Validator.** Chat can never bypass validation, or
        "just add that I led the team" writes an unsupported claim straight
        into the document (AC-R5.2).

        If the instruction needs a fact that does not exist, the Validator cuts
        whatever the Writer invented and says why — which is the honest answer,
        and the cue to add the fact to the knowledge base rather than to the
        resume.
        """
        requirements = run.read("requirements")
        merged = run.read("merged")
        selection = Selection(
            facts=[
                SelectedFact(
                    fact_id=f["fact_id"],
                    chosen_by=f["chosen_by"],
                    requirement_ids=f.get("requirement_ids") or [],
                    strength=f.get("strength") or "moderate",
                    reason=f.get("reason"),
                    argument=f.get("argument"),
                    depth=f.get("depth"),
                )
                for f in merged["facts"]
            ],
            rejected=merged.get("considered_and_rejected") or [],
            tag_proposals=merged.get("tag_proposals") or [],
        )

        history = run.read("chat") if run.has("chat") else []
        if not already_recorded:
            # Written before the Writer is called, not after. A revision takes a
            # minute or two, and until now the person's own message was missing
            # from the conversation for all of it.
            history.append({"role": "user", "text": instruction})
            run.write("chat", history)

        previous = run.read("draft")
        prompt = (
            f"{_requirements_block(requirements)}\n\n"
            f"{_selection_block(selection)}\n\n"
            "# YOUR PREVIOUS DRAFT\n\n"
            f"{json.dumps(previous, indent=2, ensure_ascii=False)}\n\n"
            "# REVISION REQUESTED\n\n"
            + "\n".join(f"- {turn['text']}" for turn in history if turn["role"] == "user")
            + "\n\nRewrite the resume applying the requested changes. Every constraint "
            "still holds: no claim that is not in a source fact, numbers only from "
            "`metrics`, and `depth` is still a ceiling. If a request needs a fact that "
            "does not exist, leave it out — do not invent it."
        )

        # The previous draft and validation are replaced, not appended to, so
        # the artifacts always describe the current state of the document.
        run.write("draft-previous", previous)
        draft = await self._call(
            "writer", prompt, cache_prefix=render_selected(self.corpus, selection.fact_ids)
        )
        run.write("draft", draft)

        # `force`, not deleting the file. The old code removed validation.json to
        # make `validate` run again — but "this run is complete" is defined as
        # "validation.json exists", so for the whole minute or two of every
        # revision the review screen (preview and chat included) was replaced by
        # the pipeline panel. The previous validation now stays until the new
        # one atomically replaces it.
        validation = await self.validate(run, draft, selection, force=True)

        # What changed is computed from the two drafts, with no model involved;
        # the model's own account is shown beside it. The account is a claim,
        # the diff is a fact — and the gap between them is worth seeing.
        changes = draft_changes(previous, draft)
        reply = (draft.get("reply") or "").strip() if isinstance(draft, dict) else ""
        history.append(
            {
                "role": "assistant",
                "text": reply or summarise(changes),
                "changes": changes,
                "cuts": validation.get("cuts") or [],
                "warnings": validation.get("warnings") or [],
                "clean": validation.get("clean"),
            }
        )
        run.write("chat", history)

        gaps = gap_report(requirements, selection)
        run.write("gaps", gaps)

        return RunResult(
            run=run,
            requirements=requirements,
            selection=selection,
            draft=draft,
            validation=validation,
            gaps=gaps,
            usage=self.usage,
            per_agent=self.per_agent,
        )


def _requirements_block(requirements: dict[str, Any]) -> str:
    lines = ["# REQUIREMENTS", ""]
    title = requirements.get("role_title")
    if title:
        lines.append(f"Role: {title} ({requirements.get('seniority', 'seniority unclear')})")
        lines.append("")
    for row in requirements.get("requirements") or []:
        quote = f" — posting says: {row['quote']!r}" if row.get("quote") else ""
        lines.append(f"- {row.get('id')} [{row.get('kind')}] {row.get('text')}{quote}")
    signals = requirements.get("signals")
    if signals:
        lines.extend(["", f"Signals: {signals}"])
    return "\n".join(lines)


def _selection_block(selection: Selection) -> str:
    lines = ["# WHY EACH FACT WAS SELECTED", ""]
    for fact in selection.facts:
        why = fact.reason or fact.argument or ""
        requirements = ", ".join(fact.requirement_ids) or "unmatched"
        lines.append(f"- {fact.fact_id} [{fact.strength}, {requirements}] {why}")
    return "\n".join(lines)
