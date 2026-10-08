"""Read the local trace log back: per agent and prompt version, what it costs."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_entries(root: Path, days: int | None = None) -> list[dict[str, Any]]:
    files = sorted((Path(root) / "traces").glob("*.jsonl"))
    if days:
        files = files[-days:]
    entries: list[dict[str, Any]] = []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line from a crash must not hide the rest
    return entries


def summarise(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        groups[(e["agent"], e["prompt_version"], e["backend"], e.get("model"))].append(e)
    rows = []
    for (agent, version, backend, model), items in sorted(groups.items()):
        n = len(items)
        usage = [i.get("usage") or {} for i in items]
        rows.append(
            {
                "agent": agent,
                "prompt_version": version,
                "backend": backend,
                "model": model,
                "calls": n,
                "errors": sum(1 for i in items if i.get("error")),
                "repairs": sum(i.get("repairs", 0) for i in items),
                "mean_seconds": round(sum(i.get("duration_s", 0) for i in items) / n, 1),
                "mean_output_tokens": round(sum(u.get("output_tokens", 0) for u in usage) / n),
                "mean_prompt_tokens": round(
                    sum(u.get("input_tokens", 0) + u.get("cache_read_tokens", 0) for u in usage) / n
                ),
            }
        )
    return rows
