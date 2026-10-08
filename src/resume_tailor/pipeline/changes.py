"""What a revision actually changed (R5).

The chat used to answer a revision with "draft revised". That says nothing: you
cannot tell whether your request was honoured, partly honoured or quietly
ignored. The model's own account of what it did is useful, but it is a claim —
so the diff here is computed from the two drafts, with no model involved, and
shown beside it.

Bullets carry no ids, so they are matched by the facts they draw from: the same
set of sources is the same bullet, reworded or not. That is the identity that
matters here, since a bullet's sources are what the Validator checks it against.
"""

from __future__ import annotations

from typing import Any


def _bullets(draft: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    rows = []
    for section in draft.get("sections") or []:
        key = section.get("role_id") or section.get("kind") or ""
        for bullet in section.get("bullets") or []:
            rows.append((key, bullet))
    return rows


def _sources(bullet: dict[str, Any]) -> frozenset[str]:
    return frozenset(bullet.get("sources") or [])


def draft_changes(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    """The differences between two drafts, in the order a reader would care about."""
    changes: list[dict[str, Any]] = []

    if (previous.get("summary") or "").strip() != (current.get("summary") or "").strip():
        changes.append(
            {
                "kind": "summary",
                "before": (previous.get("summary") or "").strip(),
                "after": (current.get("summary") or "").strip(),
            }
        )

    before = _bullets(previous)
    after = _bullets(current)
    used: set[int] = set()

    for role, bullet in after:
        match = next(
            (
                i
                for i, (old_role, old) in enumerate(before)
                if i not in used and old_role == role and _sources(old) == _sources(bullet)
            ),
            None,
        )
        if match is None:
            changes.append(
                {
                    "kind": "added",
                    "role_id": role,
                    "lead": bullet.get("lead"),
                    "after": bullet.get("text"),
                }
            )
            continue
        used.add(match)
        old = before[match][1]
        if (old.get("text") or "").strip() != (bullet.get("text") or "").strip():
            changes.append(
                {
                    "kind": "changed",
                    "role_id": role,
                    "lead": bullet.get("lead"),
                    "before": old.get("text"),
                    "after": bullet.get("text"),
                }
            )

    for i, (role, old) in enumerate(before):
        if i not in used:
            changes.append(
                {
                    "kind": "removed",
                    "role_id": role,
                    "lead": old.get("lead"),
                    "before": old.get("text"),
                }
            )

    # Order is a change a reader notices ("lead with the trading engine") and a
    # text diff cannot see, so it is checked separately for the survivors.
    kept_before = [(r, _sources(b)) for i, (r, b) in enumerate(before) if i in used]
    kept_after = [
        (r, _sources(b))
        for r, b in after
        if any(r == r2 and _sources(b) == s2 for r2, s2 in kept_before)
    ]
    if kept_before != kept_after and len(kept_before) > 1:
        changes.append({"kind": "reordered"})

    skills_before = {g.get("group"): g.get("items") for g in previous.get("skills") or []}
    skills_after = {g.get("group"): g.get("items") for g in current.get("skills") or []}
    if skills_before != skills_after:
        changes.append({"kind": "skills", "before": skills_before, "after": skills_after})

    return changes


def summarise(changes: list[dict[str, Any]]) -> str:
    """One line for when the model supplied no account of its own."""
    if not changes:
        return "I made no changes to the draft."
    counts: dict[str, int] = {}
    for change in changes:
        counts[change["kind"]] = counts.get(change["kind"], 0) + 1
    parts = []
    for kind, label in (
        ("changed", "reworded"),
        ("added", "added"),
        ("removed", "removed"),
    ):
        if counts.get(kind):
            n = counts[kind]
            parts.append(f"{n} bullet{'s' if n != 1 else ''} {label}")
    if counts.get("summary"):
        parts.append("the summary rewritten")
    if counts.get("reordered"):
        parts.append("bullets reordered")
    if counts.get("skills"):
        parts.append("skills regrouped")
    return "Done: " + ", ".join(parts) + "."
