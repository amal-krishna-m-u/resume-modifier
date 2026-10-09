"""OpenRouter as a first-class metered backend (spec-06 §3.1).

Same wire protocol as `openai_compat` — `POST /v1/chat/completions` — with the
defaults this pipeline actually needs: a 1M window so the context gate does not
fire on a normal corpus, native JSON schema, and an auth error that names
`OPENROUTER_API_KEY`.

Default model is GLM 5.3 Flash: strong enough for Selector/Recall/Validator
(the agents that degrade silently), cheap enough that a five-agent run on the
current corpus is a couple of cents. Lab does not matter — Qwen and DeepSeek
are one Settings change away. See spec-06 §6.
"""

from __future__ import annotations

from .base import BackendCapabilities, HealthReport
from .openai_compat import OpenAICompatRunner

#: Live OpenRouter slug. Picked 2026-10-09: 1M context, structured outputs,
#: Artificial Analysis intelligence 41.8, $0.15 / $0.50 per 1M tokens.
#: Same quality band as Haiku 5.5 without pinning the tool to one lab.
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
BASE_URL = "https://openrouter.ai/api/v1"
API_KEY_ENV = "OPENROUTER_API_KEY"
CONTEXT_TOKENS = 1_000_000


class OpenRouterRunner(OpenAICompatRunner):
    name = "openrouter"

    def __init__(self, model: str | None = None, *, timeout: int = 600) -> None:
        super().__init__(
            BASE_URL,
            model or DEFAULT_MODEL,
            api_key_env=API_KEY_ENV,
            extra_headers={
                "HTTP-Referer": "https://openrouter.ai",
                "X-Title": "resume-tailor",
            },
            context_tokens=CONTEXT_TOKENS,
            native_json_schema=True,
            timeout=timeout,
        )
        self.capabilities = BackendCapabilities(
            min_context_tokens=CONTEXT_TOKENS,
            harness_overhead=0,
            native_json_schema=True,
            prompt_caching=False,
            cost_per_run="metered",
        )

    async def healthcheck(self) -> HealthReport:
        if not self.api_key:
            return HealthReport(
                self.name,
                False,
                API_KEY_ENV,
                f"{API_KEY_ENV} is not set",
                model=self.model,
            )
        report = await super().healthcheck()
        return HealthReport(
            self.name,
            report.ok,
            API_KEY_ENV,
            report.detail,
            model=self.model,
        )
