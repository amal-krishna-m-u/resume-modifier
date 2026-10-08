"""The five-agent run, against FakeRunner (spec-02 §4).

No network, no cost, deterministic. Orchestration, resumability and prompt
ordering are logic worth testing, and testing them against a live model would
make the suite slow enough that it stopped being run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor.config import Config
from resume_tailor.kb.loader import load_corpus
from resume_tailor.pipeline.artifacts import Run, run_slug, slugify
from resume_tailor.pipeline.orchestrator import Pipeline
from resume_tailor.runtime.base import BackendError, ContextExceeded
from resume_tailor.runtime.fake import FakeRunner

POSTING = "Senior Backend Engineer\nWe need Python and event-driven systems."

REQUIREMENTS = {
    "role_title": "Senior Backend Engineer",
    "seniority": "senior",
    "requirements": [
        {
            "id": "RQ1",
            "text": "Python",
            "kind": "required",
            "source": "explicit",
            "quote": "We need Python",
        },
        {
            "id": "RQ2",
            "text": "Event-driven systems",
            "kind": "required",
            "source": "explicit",
            "quote": "event-driven systems",
        },
    ],
    "signals": {"stack": ["python"]},
}

SELECTION = {
    "selected": [
        {
            "fact_id": "acme-pipeline",
            "requirement_ids": ["RQ1"],
            "strength": "strong",
            "reason": "Built the ingestion pipeline in Python",
            "depth": "working",
        }
    ],
    "considered_and_rejected": [],
}

RECALL = {"additions": [], "tag_proposals": [], "concurrences": ["acme-pipeline"]}

DRAFT = {
    "summary": "Backend engineer.",
    "summary_sources": ["acme-pipeline"],
    "sections": [
        {
            "kind": "experience",
            "role_id": "acme-engineer",
            "bullets": [
                {
                    "lead": "Ingestion",
                    "text": "Built the pipeline.",
                    "sources": ["acme-pipeline"],
                    "metrics_used": ["60%"],
                }
            ],
        }
    ],
    "skills": [{"group": "Languages", "items": ["Python"], "sources": ["acme-pipeline"]}],
}

VALIDATION = {"verdict": "clean", "cuts": [], "warnings": [], "clean": True}

REPLIES = {
    "analyst": REQUIREMENTS,
    "selector": SELECTION,
    "recall": RECALL,
    "writer": DRAFT,
    "validator": VALIDATION,
}


@pytest.fixture
def pipeline_and_run(kb: Path, tmp_path: Path):
    runner = FakeRunner(REPLIES)
    corpus = load_corpus(kb)
    run = Run.create(tmp_path / "runs", "2026-10-07-test")
    return Pipeline(runner, corpus, Config()), run, runner


# -- the happy path --------------------------------------------------------


async def test_a_full_run_produces_every_artifact(pipeline_and_run) -> None:
    pipeline, run, _ = pipeline_and_run
    result = await pipeline.run(run, POSTING)

    assert result.requirements["role_title"] == "Senior Backend Engineer"
    assert result.selection.fact_ids == ["acme-pipeline"]
    assert result.clean
    for stage in (
        "posting",
        "requirements",
        "selection",
        "recall",
        "merged",
        "draft",
        "validation",
        "gaps",
        "usage",
    ):
        assert run.has(stage), stage


async def test_every_agent_is_called_once(pipeline_and_run) -> None:
    pipeline, run, runner = pipeline_and_run
    await pipeline.run(run, POSTING)
    assert set(runner.calls) == {"analyst", "selector", "recall", "writer", "validator"}
    assert all(len(calls) == 1 for calls in runner.calls.values())


async def test_usage_is_accumulated_across_agents(pipeline_and_run) -> None:
    """Cost accrues visibly during a run rather than being discovered when a
    rate limit lands (RK-2)."""
    pipeline, run, _ = pipeline_and_run
    result = await pipeline.run(run, POSTING)
    assert result.usage.input_tokens == 5 * 100
    assert set(result.per_agent) == {"analyst", "selector", "recall", "writer", "validator"}


# -- the invariant that makes caching work ---------------------------------


async def test_the_corpus_comes_before_the_posting(pipeline_and_run) -> None:
    """spec-03 §6. The corpus is the stable prefix across both selection calls
    and across runs in a session; ordering it last would silently cost a full
    re-read every time."""
    pipeline, run, runner = pipeline_and_run
    await pipeline.run(run, POSTING)

    for agent in ("selector", "recall"):
        prompt = runner.calls[agent][0]
        assert prompt.index("# KNOWLEDGE BASE") < prompt.index("# REQUIREMENTS"), agent


async def test_selection_sees_full_fact_bodies(pipeline_and_run) -> None:
    """R11: selection reads everything, never an index."""
    pipeline, run, runner = pipeline_and_run
    await pipeline.run(run, POSTING)
    assert "Built the pipeline." in runner.calls["selector"][0]


async def test_the_writer_gets_a_narrow_set_not_the_whole_corpus(pipeline_and_run) -> None:
    """Selection and writing have opposite information needs (spec-02 §2):
    irrelevant material makes bullets blander."""
    pipeline, run, runner = pipeline_and_run
    await pipeline.run(run, POSTING)
    assert "# SELECTED CONTENT" in runner.calls["writer"][0]
    assert "# KNOWLEDGE BASE" not in runner.calls["writer"][0]


async def test_recall_is_told_what_was_chosen_but_not_why(kb: Path, tmp_path: Path) -> None:
    """spec-02 §3.3. Handed the Selector's argument, a second pass mostly
    agrees with it — and a second pass that agrees is worth nothing."""
    runner = FakeRunner(REPLIES)
    pipeline = Pipeline(runner, load_corpus(kb), Config())
    run = Run.create(tmp_path / "runs", "seq")

    await pipeline.run(run, POSTING, concurrent=False)
    prompt = runner.calls["recall"][0]
    assert "acme-pipeline" in prompt
    assert "Built the ingestion pipeline in Python" not in prompt  # the reason


# -- resumability ----------------------------------------------------------


async def test_a_completed_stage_is_not_rerun(kb: Path, tmp_path: Path) -> None:
    """With both selection passes reading the full corpus, restarting because
    the Writer failed would re-spend the two most expensive calls for nothing."""
    run = Run.create(tmp_path / "runs", "resumable")
    failing = FakeRunner(REPLIES, fail_on={"writer": BackendError("writer died")})
    corpus = load_corpus(kb)

    with pytest.raises(BackendError):
        await Pipeline(failing, corpus, Config()).run(run, POSTING)
    assert run.has("merged") and not run.has("draft")

    resumed = FakeRunner(REPLIES)
    result = await Pipeline(resumed, corpus, Config()).run(run, POSTING)

    assert result.clean
    assert "analyst" not in resumed.calls  # skipped, already on disk
    assert "selector" not in resumed.calls
    assert "writer" in resumed.calls


async def test_resuming_restores_the_merged_selection(kb: Path, tmp_path: Path) -> None:
    run = Run.create(tmp_path / "runs", "restore")
    corpus = load_corpus(kb)
    first = await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)
    second = await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)
    assert first.selection.fact_ids == second.selection.fact_ids


# -- the context gate ------------------------------------------------------


async def test_a_corpus_that_does_not_fit_refuses_before_spending_anything(
    kb: Path, tmp_path: Path
) -> None:
    """Discovering it on the Selector call would mean the Analyst's tokens
    were already spent on a run that cannot complete."""
    from dataclasses import replace

    runner = FakeRunner(REPLIES)
    runner.capabilities = replace(runner.capabilities, min_context_tokens=10)
    run = Run.create(tmp_path / "runs", "too-big")

    with pytest.raises(ContextExceeded):
        await Pipeline(runner, load_corpus(kb), Config()).run(run, POSTING)
    assert runner.calls == {}


# -- artifacts -------------------------------------------------------------


def test_slugs_are_lowercase_and_safe() -> None:
    """Lowercase is not cosmetic: APFS is case-insensitive, so `Acme` and
    `acme` must not become two directories."""
    assert slugify("Böhler & Co.") == "bohler-co"
    assert slugify("Senior Engineer / Platform") == "senior-engineer-platform"
    assert slugify("!!!") == "run"


def test_run_slug_leads_with_the_date_so_it_sorts() -> None:
    from datetime import date

    slug = run_slug("ML Engineer", "Acme", on=date(2026, 10, 7))
    assert slug.startswith("2026-10-07-")
    assert "acme" in slug and "ml-engineer" in slug


def test_a_second_run_never_overwrites_the_first(tmp_path: Path) -> None:
    """Re-running the same posting is how you compare two attempts; silently
    overwriting destroys the comparison."""
    first = Run.create(tmp_path / "runs", "same")
    second = Run.create(tmp_path / "runs", "same")
    assert first.directory != second.directory
    assert second.id == "same-2"


def test_artifacts_are_written_atomically(tmp_path: Path) -> None:
    """An interrupted write must not leave a truncated artifact that the
    resume path then reads as complete."""
    run = Run.create(tmp_path / "runs", "atomic")
    run.write("requirements", REQUIREMENTS)
    assert list(run.directory.glob("*.tmp")) == []
    assert json.loads(run.path("requirements").read_text())["role_title"]


def test_unknown_stage_names_the_real_ones(tmp_path: Path) -> None:
    run = Run.create(tmp_path / "runs", "stages")
    with pytest.raises(ValueError, match="requirements"):
        run.path("nonsense")


# -- chat revision ---------------------------------------------------------

REVISED = {
    "summary": "Revised.",
    "sections": [
        {
            "kind": "experience",
            "role_id": "acme-engineer",
            "bullets": [{"text": "Shorter.", "sources": ["acme-pipeline"]}],
        }
    ],
}


async def test_a_revision_always_revalidates(kb: Path, tmp_path: Path) -> None:
    """AC-R5.2. Chat cannot bypass validation, or "just add that I led the
    team" writes an unsupported claim straight into the document."""
    run = Run.create(tmp_path / "runs", "revise")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)

    runner = FakeRunner({**REPLIES, "writer": REVISED})
    result = await Pipeline(runner, corpus, Config()).revise(run, "Make it shorter.")

    assert "writer" in runner.calls
    assert "validator" in runner.calls, "the validator must run again after a revision"
    assert result.draft["summary"] == "Revised."


async def test_the_revision_prompt_carries_the_previous_draft(kb: Path, tmp_path: Path) -> None:
    run = Run.create(tmp_path / "runs", "revise-prompt")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)

    runner = FakeRunner({**REPLIES, "writer": REVISED})
    await Pipeline(runner, corpus, Config()).revise(run, "Lead with the pipeline.")

    prompt = runner.calls["writer"][0]
    assert "YOUR PREVIOUS DRAFT" in prompt
    assert "Lead with the pipeline." in prompt
    assert "do not invent it" in prompt


async def test_revisions_accumulate_in_the_prompt(kb: Path, tmp_path: Path) -> None:
    """A second instruction must not silently undo the first."""
    run = Run.create(tmp_path / "runs", "revise-twice")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)

    for instruction in ("Drop the award.", "Lead with RAG."):
        runner = FakeRunner({**REPLIES, "writer": REVISED})
        await Pipeline(runner, corpus, Config()).revise(run, instruction)

    prompt = runner.calls["writer"][0]
    assert "Drop the award." in prompt and "Lead with RAG." in prompt


async def test_the_previous_draft_is_kept_for_comparison(kb: Path, tmp_path: Path) -> None:
    run = Run.create(tmp_path / "runs", "revise-keep")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)
    await Pipeline(FakeRunner({**REPLIES, "writer": REVISED}), corpus, Config()).revise(
        run, "Shorter."
    )
    assert run.has("draft-previous")
    assert run.read("draft-previous")["summary"] == "Backend engineer."


# -- what the person sees of a revision ------------------------------------


async def test_the_persons_message_is_on_disk_before_the_writer_runs(
    kb: Path, tmp_path: Path
) -> None:
    """A revision takes a minute or two. Until now the person's own message was
    missing from the conversation for all of it."""
    run = Run.create(tmp_path / "runs", "recorded-first")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)

    seen: list[list] = []

    def writer(_prompt: str):
        seen.append(run.read("chat"))  # what is on disk at the moment it is called
        return REVISED

    await Pipeline(FakeRunner({**REPLIES, "writer": writer}), corpus, Config()).revise(
        run, "Make it shorter."
    )
    assert seen[0][-1] == {"role": "user", "text": "Make it shorter."}


async def test_the_assistants_answer_carries_what_actually_changed(
    kb: Path, tmp_path: Path
) -> None:
    run = Run.create(tmp_path / "runs", "diffed")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)
    await Pipeline(FakeRunner({**REPLIES, "writer": REVISED}), corpus, Config()).revise(
        run, "Shorter."
    )
    turn = run.read("chat")[-1]
    assert turn["role"] == "assistant"
    assert any(c["kind"] == "summary" for c in turn["changes"])
    assert turn["text"], "never an empty answer"


async def test_the_writers_own_account_is_shown_when_it_gives_one(kb: Path, tmp_path: Path) -> None:
    run = Run.create(tmp_path / "runs", "account")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)
    reply = {**REVISED, "reply": "I couldn't add that you led a team: no fact says so."}
    await Pipeline(FakeRunner({**REPLIES, "writer": reply}), corpus, Config()).revise(run, "x")
    assert run.read("chat")[-1]["text"].startswith("I couldn't add that you led a team")


async def test_without_an_account_the_computed_diff_speaks(kb: Path, tmp_path: Path) -> None:
    run = Run.create(tmp_path / "runs", "fallback")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)
    await Pipeline(FakeRunner({**REPLIES, "writer": REVISED}), corpus, Config()).revise(run, "x")
    assert run.read("chat")[-1]["text"].startswith("Done:")


async def test_validator_findings_reach_the_conversation(kb: Path, tmp_path: Path) -> None:
    """A cut claim should be explained where the person asked for it, not only
    on a different tab."""
    run = Run.create(tmp_path / "runs", "findings")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)
    cut = {
        "verdict": "changes_made",
        "clean": False,
        "warnings": [],
        "cuts": [{"bullet": "Led a team.", "reason": "no source says so"}],
    }
    await Pipeline(
        FakeRunner({**REPLIES, "writer": REVISED, "validator": cut}), corpus, Config()
    ).revise(run, "Say I led a team.")
    turn = run.read("chat")[-1]
    assert turn["clean"] is False
    assert turn["cuts"][0]["reason"] == "no source says so"


# -- run names ---------------------------------------------------------------


def test_a_run_with_no_known_role_is_not_called_untitled() -> None:
    """The web form sent only a posting and a company, so every run it created
    was folder-named "…-untitled"."""
    from datetime import date

    slug = run_slug(None, "Visa", on=date(2026, 10, 8))
    assert slug == "2026-10-08-visa"
    assert "untitled" not in slug
    assert run_slug(None, None, on=date(2026, 10, 8)) == "2026-10-08-posting"


@pytest.mark.parametrize(
    ("posting", "expected"),
    [
        ("Senior Backend Engineer\nWe are hiring.", "Senior Backend Engineer"),
        ("# Staff ML Engineer\n\nAbout us", "Staff ML Engineer"),
        ("Job Title: Platform Engineer\nLocation: Remote", "Platform Engineer"),
        ("**Data Engineer**\n", "Data Engineer"),
        ("\n\n  Role - Site Reliability Engineer  \n", "Site Reliability Engineer"),
        ("", None),
        ("a\nb", None),
    ],
)
def test_the_role_is_guessed_from_the_top_of_the_posting(posting: str, expected) -> None:
    from resume_tailor.pipeline.artifacts import guess_role

    assert guess_role(posting) == expected


def test_a_run_is_titled_by_the_analysts_reading_first(tmp_path: Path) -> None:
    """The folder name is permanent and was never meant to be the label."""
    run = Run.create(tmp_path / "runs", "2026-10-07-visa-untitled")
    assert run.title() == "Visa"  # humanised id, nothing else known
    run.write("posting", "SW Engineer (Java)\nDetails.")
    assert run.title() == "SW Engineer (Java)"  # then the top of the posting
    run.write("requirements", {"role_title": "Software Engineer, GenAI"})
    assert run.title() == "Software Engineer, GenAI"  # then what the Analyst understood
    run.write("meta", {"title": "My own name for it"})
    assert run.title() == "My own name for it"  # a person's choice outranks all of it


def test_the_id_is_made_readable_as_a_last_resort() -> None:
    from resume_tailor.pipeline.artifacts import humanise_id

    assert humanise_id("2026-10-07-visa-untitled") == "Visa"
    assert humanise_id("2026-10-07-hirojet-1-untitled") == "Hirojet"
    assert humanise_id("2026-10-08-acme-ml-engineer") == "Acme Ml Engineer"


def test_a_leading_about_us_is_not_taken_for_the_title() -> None:
    """Boilerplate openers are skipped. The guess is only for naming a folder
    and labelling a run until the Analyst reads it properly, so being merely
    sensible is enough — it need not be right."""
    from resume_tailor.pipeline.artifacts import guess_role

    assert guess_role("About us\nWe build things.") != "About us"


# -- a revision must not make the run look unfinished ------------------------


async def test_the_previous_validation_survives_a_revision(kb: Path, tmp_path: Path) -> None:
    """Found by using it. A run counts as complete when validation.json exists,
    and the revise path deleted that file to force a re-run — so for the whole
    minute or two of every revision the review screen, with its preview and
    chat, was replaced by the pipeline panel."""
    run = Run.create(tmp_path / "runs", "stays-complete")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)

    present_during: list[bool] = []

    def writer(_prompt: str):
        present_during.append(run.has("validation"))
        return REVISED

    def validator(_prompt: str):
        present_during.append(run.has("validation"))
        return VALIDATION

    await Pipeline(
        FakeRunner({**REPLIES, "writer": writer, "validator": validator}), corpus, Config()
    ).revise(run, "Shorter.")

    assert present_during == [True, True], "validation.json vanished mid-revision"


async def test_the_new_validation_replaces_the_old_one(kb: Path, tmp_path: Path) -> None:
    """Keeping the file must not mean keeping the verdict."""
    run = Run.create(tmp_path / "runs", "replaced")
    corpus = load_corpus(kb)
    await Pipeline(FakeRunner(REPLIES), corpus, Config()).run(run, POSTING)
    assert run.read("validation")["clean"] is True

    cut = {
        "verdict": "changes_made",
        "clean": False,
        "warnings": [],
        "cuts": [{"bullet": "x", "reason": "unsupported"}],
    }
    await Pipeline(
        FakeRunner({**REPLIES, "writer": REVISED, "validator": cut}), corpus, Config()
    ).revise(run, "Say I led a team.")
    assert run.read("validation")["clean"] is False
