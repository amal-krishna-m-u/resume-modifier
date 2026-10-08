"""The knowledge-base chat: talk about your career, review proposed changes.

Implements AC-R13.2 and spec-04 §6.8. The curator agent turns what you say into
**proposals**; nothing is written until you accept one, and accepting goes
through the same validated write path as the form and the raw editor
(AC-R13.3). So the chat is a faster way to *draft* an entry, never a way around
the checks.

Three properties are what keep "I don't make mistakes" true:

1. **Proposals are diffs, not files.** The model supplies only what changes
   (`add_tags`, `body_append`, …) and `compose.apply_changes` applies it
   mechanically, so a model that "tidies" a date or drops a tag cannot do it.
2. **Validation runs before you look.** Each proposal carries its errors and
   warnings; an invalid one cannot be accepted.
3. **Stale proposals are refused.** An update records the hash of the file it
   was built against; if the file has changed since, accepting is a conflict
   rather than a silent overwrite.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..agents.specs import build_spec
from ..config import Config
from ..kb.compose import apply_changes, compose_entry, join_todo, split_todo
from ..kb.loader import Corpus, parse_entry
from ..kb.paths import PathEscape, entry_path
from ..kb.schema import TYPE_DIRS
from ..kb.write import (
    NotFound,
    ValidationFailed,
    WriteError,
    compose,
    content_hash,
    dry_run,
    write_entry,
)
from ..runtime.base import RunnerBackend
from .corpus import estimate_tokens, render_corpus

#: Turns of history sent to the model. Older ones are on disk but rarely
#: change what to propose next, and each costs prompt tokens on every call.
HISTORY_TURNS = 12

#: The conversation about the knowledge base as a whole.
GLOBAL_SCOPE = "kb"

_SCOPE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ------------------------------------------------------------------- store


class ChatStore:
    """A conversation, as one JSON file under `chats/`.

    A file rather than memory, so it survives a restart and so returning to the
    page after navigating away shows what happened — the same lesson as run
    progress. Gitignored: it is a record of your career in your own words.

    **Scoped.** There is one conversation per entry being edited, plus one for
    the knowledge base as a whole. Showing the whole history inside every
    entry's editor would be noise, and "add that it served 2,000 users" only
    means something next to the entry it is about.
    """

    def __init__(self, directory: Path, scope: str = GLOBAL_SCOPE) -> None:
        # The scope becomes part of a filename, and comes from a URL.
        if not _SCOPE.match(scope):
            raise ValueError(f"{scope!r} is not a valid conversation scope")
        self.directory = directory
        self.scope = scope
        stem = "kb-chat" if scope == GLOBAL_SCOPE else f"kb-chat--{scope}"
        self.stem = stem
        self.path = directory / f"{stem}.json"

    def load(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        return data if isinstance(data, list) else []

    def save(self, turns: list[dict[str, Any]]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(turns, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def append(self, turn: dict[str, Any]) -> list[dict[str, Any]]:
        turns = self.load()
        turns.append(turn)
        self.save(turns)
        return turns

    def archive(self) -> Path | None:
        """Start a fresh conversation without destroying the old one."""
        if not self.path.is_file():
            return None
        target = self.directory / f"{self.stem}-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
        os.replace(self.path, target)
        return target

    def find(self, proposal_id: str) -> tuple[list[dict], dict, dict] | None:
        turns = self.load()
        for turn in turns:
            for proposal in turn.get("proposals") or []:
                if proposal.get("id") == proposal_id:
                    return turns, turn, proposal
        return None


# --------------------------------------------------------------- proposals


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _visible_body(body: str) -> str:
    return split_todo(body)[0]


def build_proposal(
    kb_dir: Path,
    raw: dict[str, Any],
    overlay: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, Any]:
    """Turn one curator proposal into a reviewable, pre-validated diff."""
    entry_type = raw.get("type")
    entry_id = raw.get("id")
    op = raw.get("op")

    proposal: dict[str, Any] = {
        "id": uuid.uuid4().hex[:8],
        "op": op,
        "type": entry_type,
        "entry_id": entry_id,
        "reason": str(raw.get("reason") or ""),
        "status": "pending",
        "title": None,
        "fields": {},
        "fields_changed": [],
        "body_before": None,
        "body_after": "",
        "body_added": None,
        "raw": "",
        "base_hash": None,
        "depends_on": [],
        "errors": [],
        "warnings": [],
        "commit": None,
    }

    def fail(message: str, field: str | None = None) -> dict[str, Any]:
        proposal["errors"].append({"code": "proposal", "field": field, "message": message})
        return proposal

    if op not in ("create", "update"):
        return fail(f"unknown operation {op!r}; expected create or update", "op")
    if entry_type not in TYPE_DIRS:
        return fail(f"unknown entry type {entry_type!r}", "type")
    if not isinstance(entry_id, str) or not entry_id:
        return fail("the proposal has no id", "id")

    try:
        path = entry_path(kb_dir, entry_type, entry_id)
    except (PathEscape, ValueError) as exc:
        return fail(str(exc), "id")

    if op == "create":
        fields = {**(raw.get("fields") or {}), "id": entry_id}
        body = str(raw.get("body") or "").strip()
        if not fields.get("title"):
            return fail("a new entry needs a title", "title")
        if path.is_file():
            proposal["errors"].append(
                {
                    "code": "exists",
                    "field": "id",
                    "message": f"{entry_id} already exists — propose an update to it instead",
                }
            )
        text = compose_entry(entry_type, fields, body)
        proposal.update(
            title=str(fields["title"]),
            fields=_json_safe(fields),
            body_after=body,
            raw=text,
        )
    else:
        if not path.is_file():
            return fail(f"there is no {entry_type} called {entry_id} to update", "id")

        current = path.read_text(encoding="utf-8")
        entry = parse_entry(path, current)
        before = _json_safe(entry.frontmatter)
        frontmatter, new_body = apply_changes(entry.frontmatter, entry.body, raw)
        after = _json_safe(frontmatter)

        changed = [
            {"field": key, "before": before.get(key), "after": after.get(key)}
            for key in dict.fromkeys([*before, *after])
            if before.get(key) != after.get(key)
        ]
        appended = raw.get("body_append")
        text = compose(frontmatter, new_body)
        proposal.update(
            title=entry.meta.title,
            fields=after,
            fields_changed=changed,
            body_before=_visible_body(entry.body),
            body_after=_visible_body(new_body),
            body_added=appended.strip() if isinstance(appended, str) and appended.strip() else None,
            raw=text,
            base_hash=content_hash(current),
        )
        if not changed and proposal["body_before"] == proposal["body_after"]:
            proposal["errors"].append(
                {"code": "noop", "field": None, "message": "this would change nothing"}
            )

    parent = proposal["fields"].get("parent")
    overlay_ids = {o_id for _t, o_id, _x in overlay}
    if parent and parent in overlay_ids and not entry_path(kb_dir, "role", parent).is_file():
        proposal["depends_on"] = [parent]

    result = dry_run(kb_dir, entry_type, entry_id, proposal["raw"], overlay)
    proposal["errors"] += result["errors"]
    proposal["warnings"] += result["warnings"]
    return proposal


def taxonomy_block(corpus: Corpus) -> str:
    """The controlled vocabulary, so the curator tags from it instead of inventing."""
    lines = ["# TAXONOMY", "", "Prefer these tags. A new one becomes a warning for the person.", ""]
    for term, definition in sorted(corpus.taxonomy.items()):
        lines.append(f"- {term} ({definition.facet}): {definition.label}")
    return "\n".join(lines)


def focus_block(kb_dir: Path, focus: dict[str, Any] | None) -> str:
    """Where the person is, so "this" and "it" have something to point at.

    Without it, "add that this handled 2,000 users" is unanswerable, and the
    assistant either guesses which entry or interrogates the person about it.
    """
    if not focus:
        return ""
    entry_id = focus.get("entry")
    if isinstance(entry_id, str) and entry_id:
        found = next(
            (t for t in TYPE_DIRS if (kb_dir / TYPE_DIRS[t] / f"{entry_id}.md").is_file()),
            None,
        )
        if found:
            return (
                "# FOCUS\n\n"
                f"The person has the {found} `{entry_id}` open in the editor. Unless they "
                "say otherwise, assume they are talking about it, and prefer proposing "
                "an update to it over creating something new."
            )
    new_type = focus.get("new")
    if isinstance(new_type, str) and new_type in TYPE_DIRS:
        parent = focus.get("parent")
        under = (
            f", under the existing entry `{parent}`" if isinstance(parent, str) and parent else ""
        )
        return (
            "# FOCUS\n\n"
            f"The person is adding a new {new_type}{under}. Propose a `create` for it "
            "and ask for whatever you need to make it accurate."
        )
    return ""


def conversation_block(turns: list[dict[str, Any]]) -> str:
    """Recent history, with what happened to each proposal.

    The statuses matter: a curator that cannot see a proposal was rejected will
    cheerfully propose it again, and one that cannot see it was accepted will
    propose a duplicate of what now exists.
    """
    if not turns:
        return "# CONVERSATION\n\n(this is the start of the conversation)"

    lines = ["# CONVERSATION", ""]
    for turn in turns[-HISTORY_TURNS:]:
        if turn.get("role") == "user":
            lines.append(f"PERSON: {turn.get('text', '')}")
            continue
        if turn.get("error"):
            lines.append("ASSISTANT: (that request failed)")
            continue
        lines.append(f"ASSISTANT: {turn.get('text', '')}")
        for proposal in turn.get("proposals") or []:
            lines.append(
                f"  [proposal: {proposal.get('op')} {proposal.get('type')} "
                f"{proposal.get('entry_id')} — {proposal.get('status')}]"
            )
        for question in turn.get("questions") or []:
            lines.append(f"  [asked: {question}]")
    return "\n".join(lines)


async def curate(
    backend: RunnerBackend,
    corpus: Corpus,
    kb_dir: Path,
    config: Config,
    history: list[dict[str, Any]],
    message: str,
    focus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One curator turn: the person's message in, an assistant turn out."""
    prefix = f"{render_corpus(corpus)}\n\n{taxonomy_block(corpus)}"
    # Refuse before spending anything if the corpus cannot fit (spec-06 §4).
    backend.capabilities.assert_corpus_fits(backend.name, estimate_tokens(prefix))

    where = focus_block(kb_dir, focus)
    prompt = "\n\n".join(
        part for part in (where, conversation_block(history), f"PERSON: {message}") if part
    )
    result = await backend.run_agent(
        build_spec("curator", config.models), prompt, cache_prefix=prefix
    )
    data = result.json if isinstance(result.json, dict) else {}

    proposals: list[dict[str, Any]] = []
    overlay: list[tuple[str, str, str]] = []
    for raw in data.get("proposals") or []:
        if not isinstance(raw, dict):
            continue
        proposal = build_proposal(kb_dir, raw, tuple(overlay))
        proposals.append(proposal)
        # Later proposals are validated as if this one were accepted, so a fact
        # under a brand-new role does not report a parent that "does not exist".
        if proposal["raw"] and proposal["op"] == "create":
            overlay.append((proposal["type"], proposal["entry_id"], proposal["raw"]))

    questions = [str(q) for q in (data.get("questions") or []) if str(q).strip()]
    return {
        "role": "assistant",
        "at": now(),
        "text": str(data.get("reply") or "").strip()
        or ("Here is what I'd propose." if proposals else "Tell me more."),
        "questions": questions,
        "proposals": proposals,
        "usage": {
            "input": result.usage.input_tokens,
            "output": result.usage.output_tokens,
            "cached": result.usage.cache_read_tokens,
        },
    }


def supersede(turns: list[dict[str, Any]], new_turn: dict[str, Any]) -> None:
    """A fresh proposal for the same entry replaces an older pending one.

    Otherwise revising a proposal by chat leaves the old version sitting there
    to be accepted by mistake — exactly the error this chat exists to prevent.
    """
    fresh = {(p["op"], p["entry_id"]) for p in new_turn.get("proposals") or []}
    for turn in turns:
        for proposal in turn.get("proposals") or []:
            if (
                proposal.get("status") == "pending"
                and (proposal["op"], proposal["entry_id"]) in fresh
            ):
                proposal["status"] = "superseded"


# ------------------------------------------------------------- accept/reject


def accept(kb_dir: Path, store: ChatStore, proposal_id: str, *, cache_dir: Path | None) -> dict:
    found = store.find(proposal_id)
    if found is None:
        raise NotFound(f"no proposal {proposal_id!r}", remedy="Reload the conversation.")
    turns, _turn, proposal = found

    if proposal["status"] != "pending":
        raise WriteError(
            f"this proposal is already {proposal['status']}",
            remedy="Ask the assistant to propose it again if you still want it.",
        )

    # Dependencies must be accepted first: a fact whose role does not exist yet
    # cannot be written, and saying so beats a bare validation error.
    accepted = {
        p["entry_id"]
        for t in turns
        for p in t.get("proposals") or []
        if p.get("status") == "accepted"
    }
    missing = [d for d in proposal.get("depends_on") or [] if d not in accepted]
    if missing:
        raise WriteError(
            f"this needs {', '.join(missing)} to exist first",
            remedy="Accept that proposal before this one.",
            detail={"depends_on": missing},
        )

    # Re-validated now, not trusted from when it was proposed: the knowledge
    # base may have changed in the meantime.
    check = dry_run(kb_dir, proposal["type"], proposal["entry_id"], proposal["raw"])
    if check["errors"]:
        raise ValidationFailed(
            f"{len(check['errors'])} validation error(s)",
            remedy="Ask the assistant to fix it — nothing was written.",
            detail=check["errors"],
        )

    result = write_entry(
        kb_dir,
        proposal["type"],
        proposal["entry_id"],
        proposal["raw"],
        base_hash=proposal.get("base_hash") if proposal["op"] == "update" else None,
        cache_dir=cache_dir,
        verb=f"{proposal['op']} (via chat)",
    )

    proposal["status"] = "accepted"
    proposal["commit"] = result.commit
    proposal["warnings"] = [
        {"code": w.code, "field": w.field, "message": w.message, "entry": w.entry_id}
        for w in result.warnings
    ]
    store.save(turns)
    return proposal


def reject(store: ChatStore, proposal_id: str) -> dict:
    found = store.find(proposal_id)
    if found is None:
        raise NotFound(f"no proposal {proposal_id!r}", remedy="Reload the conversation.")
    turns, _turn, proposal = found
    if proposal["status"] == "pending":
        proposal["status"] = "rejected"
        store.save(turns)
    return proposal


# `join_todo` is re-exported for callers that build bodies themselves.
__all__ = ["ChatStore", "accept", "build_proposal", "curate", "join_todo", "reject", "supersede"]
