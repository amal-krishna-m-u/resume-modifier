"""Fit ranks existing resumes locally. A backend posting should beat a
frontend one against a second backend JD, and gaps should surface skills the
resume never mentioned — without calling a model."""

from __future__ import annotations

from pathlib import Path

from resume_tailor.pipeline.artifacts import Run
from resume_tailor.pipeline.fit import REUSE_FLOOR, cues, fit, tokens

BACKEND_JD = """
Senior Backend Engineer
We need someone who has built REST APIs in Go or Java, PostgreSQL, and
distributed systems. Required: Kafka, observability, CI/CD, and experience
running production services on Kubernetes.
Must have designed event-driven architecture.
"""

FRONTEND_JD = """
Frontend Engineer
Develop high-quality and responsive user interfaces using HTML, CSS, and
JavaScript. Required: React, SASS, WCAG, and collaboration with designers
on wireframes. Must have experience with Grunt or Gulp.
"""

OTHER_JD = """
Staff Accountant
Prepare monthly close, reconciliations, and GAAP reporting. Required: CPA,
Excel, NetSuite, and accounts payable workflows.
"""


def _complete_run(root: Path, slug: str, posting: str, summary: str, bullet: str) -> Run:
    run = Run.create(root / "runs", slug)
    run.write("posting", posting)
    run.write(
        "draft",
        {
            "summary": summary,
            "sections": [
                {
                    "kind": "experience",
                    "bullets": [{"lead": "Delivery", "text": bullet, "sources": ["x"]}],
                }
            ],
        },
    )
    run.write("validation", {"verdict": "clean", "cuts": [], "warnings": []})
    run.write("requirements", {"role_title": posting.strip().splitlines()[0]})
    return run


def test_a_backend_jd_reuses_the_backend_resume(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _complete_run(
        tmp_path,
        "backend",
        BACKEND_JD,
        "Backend engineer focused on Go APIs, PostgreSQL and Kubernetes.",
        "Designed event-driven services with Kafka and CI/CD on Kubernetes.",
    )
    _complete_run(
        tmp_path,
        "frontend",
        FRONTEND_JD,
        "Frontend engineer writing React and CSS.",
        "Built responsive user interfaces with React and WCAG.",
    )
    ranked = fit(BACKEND_JD.replace("Senior", "Lead"), runs, tmp_path / "applications")
    assert ranked
    assert ranked[0].card.id.startswith("backend")
    assert ranked[0].recommend
    assert ranked[0].score >= REUSE_FLOOR


def test_an_unrelated_posting_is_not_recommended(tmp_path: Path) -> None:
    _complete_run(
        tmp_path,
        "backend",
        BACKEND_JD,
        "Backend engineer focused on Go APIs.",
        "Ran PostgreSQL and Kafka in production.",
    )
    ranked = fit(OTHER_JD, tmp_path / "runs", tmp_path / "applications")
    assert ranked
    assert not ranked[0].recommend


def test_gaps_call_out_what_the_resume_never_said(tmp_path: Path) -> None:
    _complete_run(
        tmp_path,
        "backend",
        BACKEND_JD,
        "Go APIs and PostgreSQL.",
        "Built REST APIs in Go with PostgreSQL.",
    )
    ranked = fit(BACKEND_JD, tmp_path / "runs", tmp_path / "applications")
    absent_text = " ".join(g.text.lower() for g in ranked[0].absent)
    # Kubernetes is in the JD; this resume never mentioned it.
    assert "kubernetes" in absent_text or any(
        g.status == "absent" for g in ranked[0].gaps if "kubernetes" in g.text.lower()
    )


def test_requirement_cues_come_from_bullets_and_must_lines() -> None:
    found = cues(BACKEND_JD)
    assert any("kubernetes" in line.lower() for line in found)
    assert tokens("the team will use Go") == ["go"]
