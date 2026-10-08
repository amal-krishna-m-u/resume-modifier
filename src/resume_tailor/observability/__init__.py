"""Tracing (OQ-10): what each agent call did, comparable across prompt versions.

Per-run artifacts already say what a run produced. They cannot say whether
prompt v2 selects better than v1, because that needs the same call recorded
with its prompt version, model, latency and tokens, in one place, across runs.
"""

from .context import current_scope, scope
from .tracing import (
    LangfuseSink,
    LocalLog,
    TracedBackend,
    check_self_hosted,
    prompt_version,
    wrap,
)

__all__ = [
    "LangfuseSink",
    "LocalLog",
    "TracedBackend",
    "check_self_hosted",
    "current_scope",
    "prompt_version",
    "scope",
    "wrap",
]
