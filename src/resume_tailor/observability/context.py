"""Which run (or eval case) the current agent calls belong to.

A contextvar rather than a parameter, so the tracing wrapper stays a drop-in
`RunnerBackend` and no agent or pipeline signature changes (AC-R15.1). asyncio
tasks inherit it, so the concurrent Selector and Recall both see the run.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_scope: ContextVar[dict[str, Any] | None] = ContextVar("trace_scope", default=None)


def current_scope() -> dict[str, Any]:
    return _scope.get() or {}


@contextmanager
def scope(**fields: Any) -> Iterator[None]:
    """`scope(run_id=…, kind="tailor")` — merged over any enclosing scope."""
    token = _scope.set({**(_scope.get() or {}), **fields})
    try:
        yield
    finally:
        _scope.reset(token)
