"""What a revision changed — computed from the drafts, not claimed by a model."""

from __future__ import annotations

from resume_tailor.pipeline.changes import draft_changes, summarise


def draft(*bullets, summary="S.", skills=None):
    return {
        "summary": summary,
        "sections": [
            {
                "kind": "experience",
                "role_id": "acme",
                "bullets": [{"text": t, "sources": list(s), "lead": t[:5]} for t, s in bullets],
            }
        ],
        "skills": skills or [],
    }


A = ("Built the pipeline.", ["f1"])
B = ("Ran the migration.", ["f2"])


def kinds(changes):
    return [c["kind"] for c in changes]


def test_identical_drafts_have_no_changes() -> None:
    assert draft_changes(draft(A, B), draft(A, B)) == []


def test_no_change_is_said_plainly() -> None:
    """A revision that did nothing should not read like a success."""
    assert summarise([]) == "I made no changes to the draft."


def test_a_reworded_bullet_is_matched_by_its_sources() -> None:
    """Bullets have no ids. The facts they draw from are what the Validator
    checks them against, so the same sources is the same bullet."""
    changes = draft_changes(draft(A), draft(("Built the ingestion pipeline.", ["f1"])))
    assert kinds(changes) == ["changed"]
    assert changes[0]["before"] == "Built the pipeline."
    assert changes[0]["after"] == "Built the ingestion pipeline."


def test_an_added_bullet() -> None:
    changes = draft_changes(draft(A), draft(A, B))
    assert kinds(changes) == ["added"] and changes[0]["after"] == "Ran the migration."


def test_a_removed_bullet() -> None:
    changes = draft_changes(draft(A, B), draft(A))
    assert kinds(changes) == ["removed"] and changes[0]["before"] == "Ran the migration."


def test_the_summary() -> None:
    changes = draft_changes(draft(A, summary="Old."), draft(A, summary="New."))
    assert kinds(changes) == ["summary"]


def test_reordering_is_a_change() -> None:
    """ "Lead with the trading engine" is a reorder, which a text diff cannot see."""
    assert kinds(draft_changes(draft(A, B), draft(B, A))) == ["reordered"]


def test_reordering_is_not_reported_when_nothing_moved() -> None:
    assert "reordered" not in kinds(draft_changes(draft(A, B), draft(A, B)))


def test_the_same_text_under_another_role_is_not_the_same_bullet() -> None:
    other = {
        "summary": "S.",
        "sections": [
            {
                "kind": "experience",
                "role_id": "elsewhere",
                "bullets": [{"text": A[0], "sources": A[1]}],
            }
        ],
    }
    assert set(kinds(draft_changes(draft(A), other))) == {"added", "removed"}


def test_skill_regrouping_is_a_change() -> None:
    before = draft(A, skills=[{"group": "Languages", "items": ["Python"]}])
    after = draft(A, skills=[{"group": "Languages", "items": ["Python", "Go"]}])
    assert kinds(draft_changes(before, after)) == ["skills"]


def test_summarise_counts_what_happened() -> None:
    text = summarise(draft_changes(draft(A, B), draft(("Reworded.", ["f1"]), ("New.", ["f9"]))))
    assert "reworded" in text and "added" in text and "removed" in text
