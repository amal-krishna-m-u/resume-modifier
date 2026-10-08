"""Building and amending entry files (spec-01 §3).

The curator agent proposes *changes*, never whole files. A model asked to
re-emit an entire file drops a tag, rewrites a date or quietly "tidies" a
comment, and nothing flags it — so the model supplies only what changes and
this module applies it to the existing file mechanically.

Formatting follows what the structured editor and the bootstrap produce
(`tags: [a, b]`, `dates: {start: …}`, metrics as a block of flow maps), so a
change shows up in git as the change and not as a reformat.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

#: Canonical key order. Anything not listed follows, in the order given.
KEY_ORDER = (
    "id",
    "type",
    "parent",
    "title",
    "org",
    "location",
    "issuer",
    "credential",
    "url",
    "employment",
    "dates",
    "tags",
    "metrics",
    "depth",
    "verifiable",
    "visibility",
    "related",
    "locked_phrasing",
    "order",
)

_BARE = re.compile(r"^[A-Za-z][\w .,&()/+-]*$")
#: Words YAML would read as something other than a string.
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~"}

#: The bootstrap leaves an HTML comment at the end of each body saying what to add.
TODO_RE = re.compile(r"\n*<!--\s*TODO:?([\s\S]*?)-->\s*$")


def scalar(value: Any) -> str:
    """One YAML scalar, quoted only when it has to be."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if _BARE.match(text) and ": " not in text and text.lower() not in _RESERVED:
        return text
    # A JSON string is a valid YAML double-quoted scalar.
    return json.dumps(text, ensure_ascii=False)


def _flow_map(data: dict[str, Any]) -> str:
    return (
        "{" + ", ".join(f"{k}: {scalar(v)}" for k, v in data.items() if v not in (None, "")) + "}"
    )


def split_todo(body: str) -> tuple[str, str | None]:
    """Separate the visible body from the bootstrap's TODO note."""
    match = TODO_RE.search(body)
    if not match:
        return body.rstrip(), None
    note = re.sub(r"\s+", " ", match.group(1)).strip()
    return body[: match.start()].rstrip(), note or None


def join_todo(text: str, note: str | None) -> str:
    return f"{text.rstrip()}\n\n<!-- TODO: {note} -->" if note else text.rstrip()


def compose_entry(entry_type: str, fields: dict[str, Any], body: str) -> str:
    """Full file text for a new entry."""
    data = {"type": entry_type, **fields}
    data.setdefault("depth", "working")
    data.setdefault("verifiable", True)
    data.setdefault("visibility", "public")
    data.setdefault("tags", [])
    data.setdefault("locked_phrasing", None)

    ordered = [k for k in KEY_ORDER if k in data] + [k for k in data if k not in KEY_ORDER]
    lines: list[str] = []
    for key in ordered:
        value = data[key]
        if key == "tags" or key == "related":
            if key == "related" and not value:
                continue
            lines.append(f"{key}: [{', '.join(scalar(v) for v in value)}]")
        elif key == "dates" and isinstance(value, dict):
            lines.append(f"dates: {_flow_map(value)}")
        elif key == "metrics":
            rows = [m for m in value if m.get("value") and m.get("what")]
            if rows:
                lines.append("metrics:")
                lines.extend(f"  - {_flow_map(m)}" for m in rows)
        elif key == "order" and value is None:
            continue
        else:
            lines.append(f"{key}: {scalar(value)}")

    return f"---\n{chr(10).join(lines)}\n---\n\n{body.strip()}\n"


# --------------------------------------------------------------- amending


def _flow_seq(values: list[Any]) -> CommentedSeq:
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq


def _flow_mapping(values: dict[str, Any]) -> CommentedMap:
    mapping = CommentedMap(values)
    mapping.fa.set_flow_style()
    return mapping


def apply_changes(frontmatter: Any, body: str, change: dict[str, Any]) -> tuple[Any, str]:
    """Apply a curator `update` to an existing entry. Returns `(frontmatter, body)`.

    Works on a deep copy of the parsed frontmatter, so comments and key order
    survive, and appends rather than replaces wherever it can — `add_tags`,
    `add_metrics` and `body_append` cannot lose what is already there, which is
    the property that makes an update safe to accept in one click.
    """
    fm = deepcopy(frontmatter)
    text, note = split_todo(body)

    for key, value in (change.get("fields") or {}).items():
        if key in ("id", "type"):
            continue  # identity is permanent
        if key in ("tags", "related") and isinstance(value, list):
            fm[key] = _flow_seq(list(value))
        elif key == "dates" and isinstance(value, dict):
            fm[key] = _flow_mapping(dict(value))
        elif key == "metrics" and isinstance(value, list):
            fm[key] = [_flow_mapping(dict(m)) for m in value]
        else:
            fm[key] = value

    added_tags = [t for t in (change.get("add_tags") or []) if isinstance(t, str)]
    if added_tags:
        tags = fm.get("tags")
        if tags is None:
            fm["tags"] = _flow_seq([])
            tags = fm["tags"]
        for tag in added_tags:
            if tag not in tags:
                tags.append(tag)

    for metric in change.get("add_metrics") or []:
        if not (isinstance(metric, dict) and metric.get("value") and metric.get("what")):
            continue
        metrics = fm.get("metrics")
        if metrics is None:
            fm["metrics"] = []
            metrics = fm["metrics"]
        if not any(
            m.get("value") == metric["value"] and m.get("what") == metric["what"] for m in metrics
        ):
            metrics.append(_flow_mapping({"value": metric["value"], "what": metric["what"]}))

    if isinstance(change.get("body"), str) and change["body"].strip():
        text = change["body"].strip()
    appended = change.get("body_append")
    if isinstance(appended, str) and appended.strip():
        text = f"{text.rstrip()}\n\n{appended.strip()}" if text.strip() else appended.strip()

    # The bootstrap's note is left in place: clearing it is the user's call,
    # made when they have answered it, not a side effect of a proposal.
    return fm, join_todo(text, note)
