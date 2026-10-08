"""What an agent call is doing right now, for the UI.

A `CallStream` is created by `TracedBackend` for each call and made current in a
contextvar, so a runner can report partial output or reasoning without any
change to the `RunnerBackend` protocol: it asks `current_stream()` and, if there
is one, hands it text. No stream means no cost.

Events go to a publisher the API installs (`set_publisher`), keyed by run id.
The same text is kept on the stream so the local log can store the reasoning.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

Publisher = Callable[[str, str, dict[str, Any]], None]

_publisher: Publisher | None = None
_current: ContextVar[CallStream | None] = ContextVar("call_stream", default=None)

#: Partial output is a snapshot, throttled: a model writing 2,000 tokens would
#: otherwise be 2,000 SSE frames, each carrying the whole text so far.
SNAPSHOT_EVERY = 0.4
#: Enough to read what a model is writing; the final output is sent whole at the end.
TAIL_CHARS = 6000


def set_publisher(publisher: Publisher | None) -> None:
    global _publisher
    _publisher = publisher


def current_stream() -> CallStream | None:
    return _current.get()


class CallStream:
    def __init__(self, run_id: str | None, agent: str, *, want_reasoning: bool = False) -> None:
        self.run_id = run_id
        self.agent = agent
        self.id = uuid.uuid4().hex[:8]
        self.want_reasoning = want_reasoning
        self.output = ""
        self.reasoning: list[str] = []
        self._last = 0.0
        self._last_thinking = 0.0
        self._thinking = ""
        self._token = None

    def __enter__(self) -> CallStream:
        self._token = _current.set(self)
        return self

    def __exit__(self, *_exc: object) -> None:
        _current.reset(self._token)

    def publish(self, event: str, **data: Any) -> None:
        if _publisher is not None and self.run_id:
            # The UI must never break a call.
            with contextlib.suppress(Exception):
                _publisher(self.run_id, event, {"id": self.id, "agent": self.agent, **data})

    # -- called by runners -----------------------------------------------------

    def delta(self, text: str) -> None:
        """Model output as it arrives (a fragment)."""
        self.output += text
        self._snapshot()

    def replace_output(self, text: str) -> None:
        """Output that arrives whole (a CLI that reports once)."""
        self.output = text
        self._snapshot(force=True)

    def thought(self, text: str) -> None:
        """A piece of reasoning the backend chose to expose."""
        text = text.strip()
        if text:
            self.reasoning.append(text)
            self.publish("reasoning", text=text)

    def thinking_fragment(self, text: str) -> None:
        """Reasoning as it is written, a fragment at a time."""
        self._thinking += text
        now = time.monotonic()
        if now - self._last_thinking >= SNAPSHOT_EVERY:
            self._last_thinking = now
            self.publish("thinking", text=self._thinking[-TAIL_CHARS:])

    @property
    def has_thoughts(self) -> bool:
        return bool(self.reasoning or self._thinking.strip())

    def close(self) -> None:
        """Turn any streamed reasoning into a finished thought."""
        if self._thinking.strip():
            self.thought(self._thinking)
            self._thinking = ""

    def _snapshot(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last >= SNAPSHOT_EVERY:
            self._last = now
            self.publish("output", text=self.output[-TAIL_CHARS:], chars=len(self.output))
