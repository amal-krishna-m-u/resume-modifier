"""The write path (spec-04 §2).

Every byte that reaches `kb/` passes through these seven steps, in order,
whether it came from the structured form, the raw editor, or an agent-proposed
diff (AC-R13.3). There is no second route, because a second route is a route
that skips a check.

    1. validate ............ spec-01 §4 rules; invalid content never reaches disk
    2. path containment .... the id becomes a path; without this it is an
                             arbitrary-write primitive
    3. base_hash ........... three writers touch these files; optimistic
                             concurrency stops one silently destroying another
    4. ruamel round-trip ... preserves comments and key order
    5. atomic replace ...... a crash mid-write cannot truncate a career record
    6. git commit .......... history, revert, reviewable diffs
    7. invalidate cache .... the derived index is rebuilt on next read

Steps 3 and 6 are the ones that look optional and are not. There really are
three writers — the browser, a text editor, and agents proposing changes — and
without `base_hash` a UI save silently overwrites a vim edit made two minutes
earlier (AC-R13.4).
"""

from __future__ import annotations

import hashlib
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .gitops import commit_file
from .index import invalidate
from .loader import ParseError, load_corpus, parse_entry
from .paths import PathEscape, entry_path
from .schema import ID_RE, TYPE_DIRS, model_for
from .validate import Issue, validate_corpus
from .yamlio import dump_yaml, parse_yaml


class WriteError(RuntimeError):
    """Base for every refusal, each carrying a remedy the user can act on."""

    code = "write_error"

    def __init__(self, message: str, *, remedy: str = "", detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.remedy = remedy
        self.detail = detail


class ValidationFailed(WriteError):
    code = "validation_failed"


class Conflict(WriteError):
    """The file changed since it was read (step 3).

    Carries both versions so the caller can show a comparison rather than
    telling the user their work is gone.
    """

    code = "conflict"

    def __init__(self, path: Path, expected: str, actual: str, current: str) -> None:
        super().__init__(
            f"{path.name} changed on disk since you loaded it.",
            remedy=(
                "Someone or something else edited this entry — a text editor, or an "
                "accepted proposal. Compare the two versions and re-save."
            ),
            detail={"expected_hash": expected, "actual_hash": actual, "current": current},
        )
        self.current = current


class NotFound(WriteError):
    code = "not_found"


class StillReferenced(WriteError):
    code = "still_referenced"


@dataclass(frozen=True)
class WriteResult:
    path: Path
    hash: str
    commit: str | None
    warnings: list[Issue]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compose(frontmatter: dict[str, Any], body: str) -> str:
    """Build the file text from frontmatter and body.

    Round-trips through ruamel so comments and key order survive. A
    `yaml.safe_dump` here would reformat every entry on every save, turning
    each UI edit into a large diff and poisoning the history AC-R8.3 depends on.
    """
    yaml_text = dump_yaml(frontmatter).rstrip("\n")
    body = body.strip("\n")
    return f"---\n{yaml_text}\n---\n\n{body}\n" if body else f"---\n{yaml_text}\n---\n"


def write_entry(
    kb_dir: Path,
    entry_type: str,
    entry_id: str,
    frontmatter: dict[str, Any] | str,
    body: str = "",
    *,
    base_hash: str | None = None,
    cache_dir: Path | None = None,
    verb: str | None = None,
) -> WriteResult:
    """Write one entry through all seven steps.

    `frontmatter` may be a mapping (structured editor) or the whole file text
    (raw editor). Both land here so neither can skip validation — the raw
    editor exists to let a user fix something the structured form cannot
    express, not to bypass the rules.
    """
    kb_dir = kb_dir.resolve()

    # -- 2. path containment, before anything touches the filesystem --------
    # Done early because `entry_path` also rejects a non-slug id, and every
    # later step assumes the target is inside kb/.
    try:
        path = entry_path(kb_dir, entry_type, entry_id)
    except PathEscape as exc:
        raise WriteError(
            str(exc),
            remedy="Ids are lowercase letters, digits and single hyphens — `ey-ase2-rag`.",
        ) from exc
    except ValueError as exc:
        raise WriteError(str(exc), remedy=f"Known types: {', '.join(sorted(TYPE_DIRS))}.") from exc

    if isinstance(frontmatter, str):
        text = frontmatter if frontmatter.endswith("\n") else frontmatter + "\n"
    else:
        # deepcopy, never dict(). ruamel attaches comments to the CommentedMap
        # itself, so `dict(mapping)` silently drops every one of them — which
        # is precisely the loss step 4 exists to prevent, reintroduced one line
        # before the round-trip that was supposed to stop it.
        data = deepcopy(frontmatter)
        data.setdefault("id", entry_id)
        data.setdefault("type", entry_type)
        text = compose(data, body)

    existed = path.is_file()

    # -- 3. base_hash ------------------------------------------------------
    if existed:
        current = path.read_text(encoding="utf-8")
        actual = content_hash(current)
        if base_hash is None:
            raise Conflict(path, "none supplied", actual, current)
        if base_hash != actual:
            raise Conflict(path, base_hash, actual, current)
    elif base_hash:
        raise NotFound(
            f"{entry_id} does not exist, but a base_hash was supplied.",
            remedy="Create it without a base_hash, or check the id.",
        )

    # -- 1. validate -------------------------------------------------------
    _validate_candidate(kb_dir, path, entry_type, entry_id, text)

    # -- 5. atomic replace -------------------------------------------------
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

    # -- 6. commit ---------------------------------------------------------
    action = verb or ("update" if existed else "create")
    commit = commit_file(kb_dir, path, f"kb: {action} {entry_id}")

    # -- 7. invalidate -----------------------------------------------------
    invalidate(cache_dir or kb_dir.parent / ".cache")

    warnings = [
        issue
        for issue in validate_corpus(load_corpus(kb_dir)).warnings
        if issue.entry_id == entry_id
    ]
    return WriteResult(path=path, hash=content_hash(text), commit=commit, warnings=warnings)


def _validate_candidate(
    kb_dir: Path, path: Path, entry_type: str, entry_id: str, text: str
) -> None:
    """Parse and validate the candidate *as part of the corpus*, not alone.

    Validating it in isolation would accept a dangling `parent` and a duplicate
    id, which are only visible against everything else — and they are two of
    the three rules that actually bite in practice.
    """
    try:
        candidate = parse_entry(path, text)
    except ParseError as exc:
        raise ValidationFailed(
            exc.message,
            remedy="Fix the frontmatter and save again. Nothing was written.",
            detail={"path": str(path)},
        ) from exc

    if candidate.meta.type != entry_type:
        raise ValidationFailed(
            f"frontmatter says type {candidate.meta.type!r} but this is a {entry_type}",
            remedy=f"Set `type: {entry_type}`, or save it as a {candidate.meta.type}.",
        )
    if candidate.meta.id != entry_id:
        raise ValidationFailed(
            f"frontmatter says id {candidate.meta.id!r} but the path says {entry_id!r}",
            remedy="Ids are permanent. To rename, create the new entry and delete the old.",
        )

    corpus = load_corpus(kb_dir)
    corpus.entries = [e for e in corpus.entries if e.path != path] + [candidate]

    report = validate_corpus(corpus)
    blocking = [i for i in report.errors if i.entry_id in (entry_id, None)]
    if blocking:
        raise ValidationFailed(
            f"{len(blocking)} validation error(s)",
            remedy="Each error names the field. Nothing was written.",
            detail=[
                {"code": i.code, "field": i.field, "message": i.message, "entry": i.entry_id}
                for i in blocking
            ],
        )


def dry_run(
    kb_dir: Path,
    entry_type: str,
    entry_id: str,
    text: str,
    overlay: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, list[dict]]:
    """Validate a candidate **without writing**, reporting warnings too.

    A proposal is shown to the user before anything is written, so it needs the
    whole picture up front: the errors that will block it, and the warnings
    (an unknown tag, say) that will not. `_validate_candidate` raises on the
    first kind and never sees the second, which is why this exists separately.
    """
    kb_dir = kb_dir.resolve()

    def issue(code: str, message: str, field: str | None = None, entry: str | None = None) -> dict:
        return {"code": code, "field": field, "message": message, "entry": entry}

    try:
        path = entry_path(kb_dir, entry_type, entry_id)
    except (PathEscape, ValueError) as exc:
        return {"errors": [issue("id", str(exc), "id")], "warnings": []}

    try:
        candidate = parse_entry(path, text)
    except ParseError as exc:
        return {"errors": [issue("parse", exc.message)], "warnings": []}

    errors: list[dict] = []
    if candidate.meta.type != entry_type:
        errors.append(
            issue("type", f"type is {candidate.meta.type!r}, expected {entry_type!r}", "type")
        )
    if candidate.meta.id != entry_id:
        errors.append(issue("id", f"id is {candidate.meta.id!r}, expected {entry_id!r}", "id"))

    corpus = load_corpus(kb_dir)

    # `overlay` is the earlier proposals from the same message, assumed
    # accepted. Without it a fact proposed under a role proposed in the same
    # breath would always report "parent does not exist".
    pending = []
    for o_type, o_id, o_text in overlay:
        try:
            pending.append(parse_entry(entry_path(kb_dir, o_type, o_id), o_text))
        except (ParseError, PathEscape, ValueError):
            continue
    replaced = {e.path for e in pending} | {path}
    corpus.entries = [e for e in corpus.entries if e.path not in replaced] + pending + [candidate]
    report = validate_corpus(corpus)

    errors += [
        issue(i.code, i.message, i.field, i.entry_id)
        for i in report.errors
        if i.entry_id in (entry_id, None)
    ]
    warnings = [
        issue(i.code, i.message, i.field, i.entry_id)
        for i in report.warnings
        if i.entry_id == entry_id
    ]
    return {"errors": errors, "warnings": warnings}


def delete_entry(
    kb_dir: Path, entry_type: str, entry_id: str, *, cache_dir: Path | None = None
) -> str | None:
    """Delete an entry, refusing while anything still points at it.

    A dangling `parent` leaves facts that render nowhere; a dangling `evidence`
    id leaves a skill with nothing behind it. Both are silent, so the refusal
    is loud.
    """
    kb_dir = kb_dir.resolve()
    path = entry_path(kb_dir, entry_type, entry_id)
    if not path.is_file():
        raise NotFound(f"{entry_id} does not exist.", remedy="Check the id.")

    corpus = load_corpus(kb_dir)
    referrers: list[str] = []
    for entry in corpus.entries:
        if entry.id == entry_id:
            continue
        if getattr(entry.meta, "parent", None) == entry_id or entry_id in entry.meta.related:
            referrers.append(entry.id)
    referrers += [s.skill for s in corpus.skills if entry_id in s.evidence]

    if referrers:
        raise StillReferenced(
            f"{entry_id} is referenced by: {', '.join(sorted(set(referrers)))}",
            remedy="Remove those references first, or the knowledge base is left inconsistent.",
            detail={"referrers": sorted(set(referrers))},
        )

    path.unlink()
    commit = commit_file(kb_dir, path, f"kb: delete {entry_id}")
    invalidate(cache_dir or kb_dir.parent / ".cache")
    return commit


def read_entry(kb_dir: Path, entry_type: str, entry_id: str) -> dict[str, Any]:
    """One entry: parsed fields, raw text and the hash a save must echo back."""
    path = entry_path(kb_dir.resolve(), entry_type, entry_id)
    if not path.is_file():
        raise NotFound(f"{entry_id} does not exist.", remedy="Check the id and type.")

    raw = path.read_text(encoding="utf-8")
    entry = parse_entry(path, raw)
    return {
        "id": entry.id,
        "type": entry.type,
        "frontmatter": entry.frontmatter,
        "body": entry.body,
        "raw": raw,
        "hash": content_hash(raw),
        "path": str(path.relative_to(kb_dir)),
    }


def validate_only(kb_dir: Path, entry_type: str, entry_id: str, text: str) -> list[dict]:
    """Dry run for `POST /api/kb/validate` — no write, no commit."""
    if not ID_RE.match(entry_id):
        return [{"code": "id-format", "message": f"{entry_id!r} is not a slug"}]
    model_for(entry_type)
    path = entry_path(kb_dir.resolve(), entry_type, entry_id)
    try:
        _validate_candidate(kb_dir.resolve(), path, entry_type, entry_id, text)
    except ValidationFailed as exc:
        return exc.detail if isinstance(exc.detail, list) else [{"message": exc.message}]
    return []


def write_yaml_file(
    kb_dir: Path, name: str, data: Any, *, base_hash: str | None = None
) -> WriteResult:
    """Write `taxonomy.yaml` or `skills.yaml` through the same steps."""
    if name not in ("taxonomy.yaml", "skills.yaml"):
        raise WriteError(f"{name!r} is not an editable knowledge-base file.")

    kb_dir = kb_dir.resolve()
    path = kb_dir / name
    text = dump_yaml(data)

    if path.is_file():
        current = path.read_text(encoding="utf-8")
        actual = content_hash(current)
        if base_hash != actual:
            raise Conflict(path, base_hash or "none supplied", actual, current)

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

    # `load_corpus` itself raises on a malformed taxonomy or skills file —
    # before validation ever runs — so the rollback has to cover that too.
    # Catching only validation errors left a broken file on disk and surfaced
    # a bare ValueError instead of a 422.
    try:
        report = validate_corpus(load_corpus(kb_dir))
        errors = report.errors
    except Exception as exc:
        errors = [Issue("error", "unreadable", str(exc))]
        report = None

    if errors:
        # Roll back: the corpus must never be left in a state the loader
        # cannot read, and these two files break *every* entry when wrong.
        if base_hash is not None:
            path.write_text(current, encoding="utf-8")
        else:
            path.unlink()
        raise ValidationFailed(
            f"{name} would break the knowledge base",
            remedy="Reverted. Fix the errors below and save again.",
            detail=[{"code": i.code, "message": i.message} for i in errors[:20]],
        )

    commit = commit_file(kb_dir, path, f"kb: update {name}")
    invalidate(kb_dir.parent / ".cache")
    return WriteResult(path=path, hash=content_hash(text), commit=commit, warnings=report.warnings)


def parse_raw(text: str) -> tuple[dict[str, Any], str]:
    """Split raw editor text into frontmatter and body."""
    from .loader import split_frontmatter

    yaml_text, body = split_frontmatter(text)
    return parse_yaml(yaml_text) or {}, body
