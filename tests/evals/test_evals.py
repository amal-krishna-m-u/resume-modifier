"""Evals (OQ-10): scoring, the validator probe, and attributable comparisons."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from resume_tailor.config import Config
from resume_tailor.evals import Case, build_case, compare, load_cases, run_eval, save_case
from resume_tailor.evals.runner import caught, inject, load_result, score_selection
from resume_tailor.kb.loader import load_corpus
from resume_tailor.pipeline.artifacts import Run
from resume_tailor.runtime.fake import FakeRunner
from tests.pipeline.test_orchestrator import (
    DRAFT,
    POSTING,
    RECALL,
    REPLIES,
    REQUIREMENTS,
    SELECTION,
    VALIDATION,
)


def make_case(**overrides) -> Case:
    base = {
        "id": "c1",
        "posting": POSTING,
        "must_include": ["acme-pipeline"],
        "baseline": ["acme-pipeline"],
        "baseline_draft": DRAFT,
        "baseline_merged": {
            "facts": [
                {
                    "fact_id": "acme-pipeline",
                    "chosen_by": "both",
                    "requirement_ids": ["RQ1"],
                    "strength": "strong",
                    "reason": "r",
                    "argument": None,
                    "depth": "working",
                }
            ],
            "considered_and_rejected": [],
            "tag_proposals": [],
        },
    }
    return Case(**{**base, **overrides})


# -- scoring --------------------------------------------------------------------


def test_recall_counts_expected_facts_found() -> None:
    case = make_case(must_include=["a", "b", "c", "d"], baseline=["a", "b", "c", "d"])
    assert score_selection(case, ["a", "b"])["recall"] == 0.5


def test_picks_the_case_forbids_are_counted() -> None:
    case = make_case(must_exclude=["x"])
    assert score_selection(case, ["acme-pipeline", "x"])["exclusions"] == 1.0


def test_stability_is_perfect_only_when_nothing_moved() -> None:
    case = make_case(must_include=["a"], baseline=["a", "b"])
    assert score_selection(case, ["a", "b"])["stability"] == 1.0
    assert score_selection(case, ["a", "z"])["stability"] < 1.0
    assert score_selection(case, [])["stability"] == 0.0


# -- the validator probe -----------------------------------------------------------


def test_the_injected_claim_is_not_in_the_original_and_cites_a_real_fact() -> None:
    bad, text = inject(DRAFT)
    bullets = bad["sections"][0]["bullets"]
    assert bullets[-1]["text"] == text and len(bullets) == len(DRAFT["sections"][0]["bullets"]) + 1
    assert bullets[-1]["sources"] == ["acme-pipeline"]
    assert text not in json.dumps(DRAFT), "injection must not mutate the baseline"


def test_catching_means_the_claim_is_cut_or_flagged() -> None:
    _, text = inject(DRAFT)
    assert caught({"cuts": [{"bullet": text, "reason": "unsupported"}]}, text)
    assert caught({"warnings": [{"bullet": text, "reason": "stretch"}]}, text)
    assert not caught({"cuts": [], "warnings": []}, text)
    assert not caught({"cuts": [{"bullet": "something else", "reason": "x"}]}, text)


# -- running -----------------------------------------------------------------------


def runner(validator) -> FakeRunner:
    return FakeRunner({**REPLIES, "validator": validator})


async def run(kb: Path, tmp_path: Path, replies: FakeRunner, label="a", cases=None):
    return await run_eval(
        tmp_path,
        replies,
        load_corpus(kb),
        Config(),
        cases or [make_case()],
        label=label,
    )


async def test_an_eval_scores_selection_and_the_probe(kb, tmp_path) -> None:
    def validator(prompt: str):
        # A competent validator cuts the fabricated bullet.
        return {
            "verdict": "changes_made",
            "clean": False,
            "cuts": [{"bullet": "Led a team of 12 engineers", "reason": "no support"}],
        }

    result = await run(kb, tmp_path, runner(validator))
    scores = result["cases"]["c1"]["scores"]
    assert scores["recall"] == 1.0 and scores["validator_catches_fabrication"] == 1.0
    assert (tmp_path / "evals" / "results" / result["file"]).is_file()


async def test_a_validator_that_waves_it_through_scores_zero(kb, tmp_path) -> None:
    """The failure the probe exists for: a Validator that rationalises a made-up
    claim as supported. It must show up as a number, not pass silently."""
    result = await run(kb, tmp_path, runner(VALIDATION))
    assert result["cases"]["c1"]["scores"]["validator_catches_fabrication"] == 0.0


async def test_a_missed_fact_is_named(kb, tmp_path) -> None:
    nothing = {"selected": [], "considered_and_rejected": []}
    fake = FakeRunner({**REPLIES, "selector": nothing, "recall": {"additions": [], "concurrences": []}})
    result = await run(kb, tmp_path, fake)
    assert result["cases"]["c1"]["missed"] == ["acme-pipeline"]
    assert result["cases"]["c1"]["scores"]["recall"] == 0.0


async def test_results_record_prompt_versions_and_backend(kb, tmp_path) -> None:
    result = await run(kb, tmp_path, runner(VALIDATION), label="baseline")
    assert set(result["prompt_versions"]) >= {"analyst", "selector", "writer", "validator"}
    assert result["backend"] == "fake" and result["reviewed_cases"] == 0


async def test_eval_calls_do_not_touch_real_runs(kb, tmp_path) -> None:
    await run(kb, tmp_path, runner(VALIDATION))
    assert not (tmp_path / "runs").exists()


async def test_every_eval_call_is_traced_under_the_case(kb, tmp_path) -> None:
    from resume_tailor.observability import LocalLog, TracedBackend
    from resume_tailor.observability.summary import read_entries

    traced = TracedBackend(runner(VALIDATION), [LocalLog(tmp_path / "traces")])
    await run(kb, tmp_path, traced, label="t")
    entries = read_entries(tmp_path)
    assert entries and all(e["kind"] == "eval" and e["label"] == "t" for e in entries)
    assert all("c1" in e["run_id"] for e in entries)


# -- comparing ------------------------------------------------------------------------


def result(label, versions, mean, backend="fake"):
    return {
        "label": label,
        "backend": backend,
        "models": {},
        "prompt_versions": versions,
        "mean": mean,
    }


def test_a_comparison_attributes_the_change_to_the_prompt_that_moved() -> None:
    a = result("v1", {"selector": "aaa", "writer": "w"}, {"recall": 0.6})
    b = result("v2", {"selector": "bbb", "writer": "w"}, {"recall": 0.8})
    diff = compare(a, b)
    assert diff["prompt_changes"] == {"selector": ("aaa", "bbb")}
    assert diff["delta"]["recall"] == 0.2


def test_identical_prompts_mean_a_delta_is_noise() -> None:
    a = result("1", {"selector": "aaa"}, {"recall": 0.6})
    b = result("2", {"selector": "aaa"}, {"recall": 0.7})
    diff = compare(a, b)
    assert not diff["prompt_changes"] and not diff["backend_changed"]


def test_backend_changes_are_reported_separately_from_prompts() -> None:
    a = result("1", {"selector": "aaa"}, {"recall": 0.6}, backend="claude_sdk")
    b = result("2", {"selector": "aaa"}, {"recall": 0.6}, backend="codex_cli")
    assert compare(a, b)["backend_changed"] == ("claude_sdk", "codex_cli")


# -- cases ------------------------------------------------------------------------------


def test_building_a_case_from_a_run_is_unreviewed_until_a_person_says_so(kb, tmp_path) -> None:
    run_ = Run.create(tmp_path / "runs", "2026-10-09-x")
    run_.write("posting", POSTING)
    run_.write("merged", make_case().baseline_merged)
    run_.write("draft", DRAFT)
    case = build_case(run_, "mine")
    assert case.id == "mine" and case.must_include == ["acme-pipeline"] and not case.reviewed


def test_cases_round_trip_and_filter(tmp_path) -> None:
    save_case(tmp_path, make_case(id="a"))
    save_case(tmp_path, make_case(id="b"))
    assert [c.id for c in load_cases(tmp_path)] == ["a", "b"]
    assert [c.id for c in load_cases(tmp_path, ["b"])] == ["b"]


def test_a_run_without_a_selection_cannot_become_a_case(tmp_path) -> None:
    with pytest.raises(ValueError, match="finish it first"):
        build_case(Run.create(tmp_path / "runs", "2026-10-09-empty"))


def test_missing_result_names_the_directory(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="results"):
        load_result(tmp_path, "nope")


_ = (REQUIREMENTS, SELECTION, RECALL, copy)


def test_a_truncated_quote_still_counts_and_a_stray_word_does_not() -> None:
    _, text = inject(DRAFT)
    assert caught({"cuts": [{"bullet": text[:30], "reason": "x"}]}, text)
    assert caught({"cuts": [{"bullet": f"Team Leadership: {text}", "reason": "x"}]}, text)
    assert not caught({"cuts": [{"bullet": "Led", "reason": "x"}]}, text)
