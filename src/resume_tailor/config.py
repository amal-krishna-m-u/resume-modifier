"""Configuration, read from `resume-tailor.toml` (spec-06 §7).

Backend selection never touches agent or pipeline code (AC-R15.1): everything
below resolves to one `RunnerBackend`, and the orchestrator sees only that.

TOML via the standard library's `tomllib`, so configuration adds no dependency.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_NAME = "resume-tailor.toml"

#: Resolved by OQ-1 on 2026-10-06: the Agent SDK works on a subscription
#: session with no API key, so it is the default. spec-06 §7's example still
#: showed `claude_cli`, which predated that result.
DEFAULT_BACKEND = "claude_sdk"


@dataclass
class ModelConfig:
    """Which model each agent gets (OQ-6, spec-06 §6).

    `validator` is separate and deliberately not the cheapest option. Selection
    and writing degrade *visibly* — missed facts show up on the review screen,
    weak prose reads as bland. A weak Validator degrades **invisibly**: it
    rationalises an unsupported claim as supported, and you find out in an
    interview.
    """

    default: str | None = None
    analyst: str | None = None
    selector: str | None = None
    recall: str | None = None
    writer: str | None = None
    validator: str | None = None
    curator: str | None = None

    def for_agent(self, name: str) -> str | None:
        return getattr(self, name, None) or self.default


@dataclass
class OpenAICompatConfig:
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5:14b"
    api_key_env: str = "OPENAI_API_KEY"
    #: The model's real window. Deliberately not generous: the context gate is
    #: what stops a small model silently producing a worse resume on a corpus
    #: it could not read (spec-06 §4).
    context_tokens: int = 32_000
    native_json_schema: bool = False


@dataclass
class Config:
    backend: str = DEFAULT_BACKEND
    models: ModelConfig = field(default_factory=ModelConfig)
    openai_compat: OpenAICompatConfig = field(default_factory=OpenAICompatConfig)
    #: One page, with overflow reported rather than cut (OQ-4, resolved
    #: 2026-10-07). Nothing is ever dropped to make a document fit.
    page_budget: int = 1
    source: Path | None = None

    @classmethod
    def load(cls, root: Path | None = None) -> Config:
        """Read `resume-tailor.toml` if present; defaults otherwise.

        A missing file is not an error. The defaults are the configuration most
        users want, and requiring a config file to run would be friction with
        one correct answer.
        """
        config = cls()
        if root is None:
            return config

        path = Path(root) / CONFIG_NAME
        if not path.is_file():
            return config

        with path.open("rb") as handle:
            data: dict[str, Any] = tomllib.load(handle)

        runtime = data.get("runtime") or {}
        config.backend = runtime.get("backend", config.backend)
        config.page_budget = int(data.get("render", {}).get("page_budget", config.page_budget))

        models = runtime.get("models") or {}
        config.models = ModelConfig(**{k: v for k, v in models.items() if hasattr(ModelConfig, k)})

        compat = runtime.get("openai_compat") or {}
        config.openai_compat = OpenAICompatConfig(
            **{k: v for k, v in compat.items() if hasattr(OpenAICompatConfig, k)}
        )
        config.source = path
        return config

    def backend_name(self) -> str:
        """Environment overrides the file, which overrides the default.

        `RUNNER_BACKEND` exists so a single run can be pointed at another
        backend without editing a file — exactly what you want when comparing
        two of them.
        """
        return os.environ.get("RUNNER_BACKEND") or self.backend
