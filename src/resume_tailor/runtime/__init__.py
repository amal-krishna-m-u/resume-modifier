"""Backend registry.

One function turns configuration into a `RunnerBackend`. The pipeline imports
nothing from this package beyond `base`, so adding a provider is a new module
and one registry entry (AC-R15.1).
"""

from __future__ import annotations

import os

from ..config import Config
from .base import (
    AgentResult,
    AgentSpec,
    BackendAuthError,
    BackendCapabilities,
    BackendError,
    ContextExceeded,
    HealthReport,
    ModelRefusedJSON,
    RunnerBackend,
    Usage,
)

__all__ = [
    "AgentResult",
    "AgentSpec",
    "BackendAuthError",
    "BackendCapabilities",
    "BackendError",
    "ContextExceeded",
    "HealthReport",
    "ModelRefusedJSON",
    "RunnerBackend",
    "Usage",
    "BACKENDS",
    "BACKEND_INFO",
    "build_backend",
]

BACKENDS = ("claude_sdk", "claude_cli", "codex_cli", "openai_compat", "fake")


#: What the Settings screen shows. `models` are suggestions only, never a
#: whitelist: model names change faster than this file does, and an empty model
#: means "that CLI's own default", which is usually right.
BACKEND_INFO: dict[str, dict] = {
    "claude_sdk": {
        "label": "Claude (Agent SDK)",
        "blurb": "Your Claude subscription through the Agent SDK. The default; leanest on tokens.",
        "login": "claude login",
        "models": ["opus", "sonnet", "haiku"],
    },
    "claude_cli": {
        "label": "Claude (CLI)",
        "blurb": "Runs the `claude` binary once per agent. Slower, same subscription.",
        "login": "claude login",
        "models": ["opus", "sonnet", "haiku"],
    },
    "codex_cli": {
        "label": "Codex (CLI)",
        "blurb": "Your ChatGPT/Codex login. Leave the model empty to use Codex's own default.",
        "login": "codex login",
        "models": [],
    },
    "openai_compat": {
        "label": "OpenAI-compatible server",
        "blurb": "Ollama, LM Studio, vLLM or any /v1 endpoint. Small windows will refuse a big KB.",
        "login": None,
        "models": [],
    },
}


def build_backend(
    config: Config | None = None, name: str | None = None, *, trace: bool = True
) -> RunnerBackend:
    """Construct the configured backend.

    Imports are deferred per branch so that a missing optional dependency —
    `claude-agent-sdk`, say — only matters to someone actually using it.
    """
    config = config or Config()
    name = name or config.backend_name()
    backend = _construct(config, name)
    if trace:
        from ..observability import wrap

        return wrap(backend, config)
    return backend


def _construct(config: Config, name: str) -> RunnerBackend:

    if name == "claude_sdk":
        from .claude_sdk import ClaudeSdkRunner

        return ClaudeSdkRunner(model=config.model_for(name))

    if name == "claude_cli":
        from .claude_cli import ClaudeCliRunner

        return ClaudeCliRunner(model=config.model_for(name))

    if name == "codex_cli":
        from .codex_cli import CodexCliRunner

        return CodexCliRunner(model=config.model_for(name))

    if name == "openai_compat":
        from .openai_compat import OpenAICompatRunner

        compat = config.openai_compat
        return OpenAICompatRunner(
            base_url=compat.base_url,
            model=compat.model,
            api_key=os.environ.get(compat.api_key_env),
            context_tokens=compat.context_tokens,
            native_json_schema=compat.native_json_schema,
        )

    if name == "fake":
        from .fake import FakeRunner

        return FakeRunner()

    raise BackendError(
        f"unknown backend {name!r}. Available: {', '.join(BACKENDS)}. "
        "Set it in resume-tailor.toml under [runtime], or with RUNNER_BACKEND."
    )
