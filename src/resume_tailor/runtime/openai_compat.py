"""Any provider speaking `POST /v1/chat/completions` (spec-06 §3.1).

One implementation covers Ollama (which serves this shape on
`localhost:11434`), OpenRouter, Groq, Together, LM Studio, vLLM and OpenAI
itself. A different provider is a `base_url` change.

The highest-return backend of the set: one file, no harness overhead at all,
and real schema enforcement where the provider supports it.

`min_context_tokens` must be set to the model's actual window. The default
below is deliberately small, because the context gate is what stops a local
model silently producing a worse resume on a corpus it cannot read, and a
generous default would defeat it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from asyncio import to_thread

from .base import (
    AgentResult,
    AgentSpec,
    BackendAuthError,
    BackendCapabilities,
    BackendError,
    HealthReport,
    Usage,
)
from .json_repair import parse_or_repair


class OpenAICompatRunner:
    name = "openai_compat"

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "qwen2.5:14b",
        *,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        extra_headers: dict[str, str] | None = None,
        context_tokens: int = 32_000,
        native_json_schema: bool = False,
        timeout: int = 600,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.api_key = os.environ.get(api_key_env) if api_key is None else api_key
        self.extra_headers = extra_headers or {}
        self.timeout = timeout
        self.capabilities = BackendCapabilities(
            min_context_tokens=context_tokens,
            harness_overhead=0,
            native_json_schema=native_json_schema,
            prompt_caching=False,
            cost_per_run="metered" if self.api_key else "free",
        )

    def _post(self, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                **self.extra_headers,
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            if exc.code in (401, 403):
                raise BackendAuthError(
                    self.name, f"an API key for this provider ({self.api_key_env})", body
                ) from exc
            raise BackendError(
                f"{self.name}: HTTP {exc.code} from {self.base_url}. {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BackendError(
                f"{self.name}: cannot reach {self.base_url} ({exc.reason}). Is the server running?"
            ) from exc

    async def _ask(self, agent: AgentSpec, prompt: str) -> tuple[str, Usage]:
        payload: dict = {
            "model": agent.model or self.model,
            "messages": [
                {"role": "system", "content": agent.system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        if agent.max_output_tokens:
            payload["max_tokens"] = agent.max_output_tokens
        if self.capabilities.native_json_schema and agent.output_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": agent.name, "schema": agent.output_schema},
            }

        data = await to_thread(self._post, payload)
        choices = data.get("choices") or []
        text = (choices[0].get("message") or {}).get("content", "") if choices else ""
        counts = data.get("usage") or {}
        return text, Usage(
            input_tokens=int(counts.get("prompt_tokens") or 0),
            output_tokens=int(counts.get("completion_tokens") or 0),
        )

    async def run_agent(
        self,
        agent: AgentSpec,
        prompt: str,
        *,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        full = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt
        text, usage = await self._ask(agent, full)

        async def reask(instruction: str) -> str:
            nonlocal usage
            retry, extra = await self._ask(agent, f"{full}\n\n{instruction}")
            usage = usage + extra
            return retry

        value, repairs = await parse_or_repair(text, agent=agent.name, reask=reask)
        return AgentResult(agent.name, text, value, usage, session_id, repairs)

    async def healthcheck(self) -> HealthReport:
        credential = f"{self.api_key_env}, or none for a local server"
        try:
            await to_thread(
                self._post,
                {
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ok"}],
                    "max_tokens": 1,
                },
            )
        except BackendError as exc:
            return HealthReport(self.name, False, credential, str(exc), model=self.model)
        return HealthReport(self.name, True, credential, self.base_url, model=self.model)
