"""OpenAI Codex CLI (spec-06 §3.3).

Verified working 2026-10-06 and again 2026-10-08 (codex-cli 0.161.0): a
272,000-token window, and strict-JSON prompts returned bare parseable objects
with no fences.

How it is invoked, and why each flag is there:

- `--skip-git-repo-check` — the CLI otherwise refuses outside a git repository.
- `--ephemeral` — **privacy.** By default Codex writes a session file for every
  call, and every call here carries the whole knowledge base. Without this, each
  tailoring run would leave the person's complete career record in
  `~/.codex/sessions`, outside every protection this project builds.
- `-s read-only` — Codex is an agentic CLI and will run shell commands if it
  decides to. This pipeline wants text in and JSON out, so it may not write.
- The prompt goes on **stdin** (`-`), not the command line. A knowledge base
  grows, and a single argument is capped at 128 KB on Linux.

Deliberately not `--ignore-user-config`: it drops the person's model setting, and
Codex then falls back to a default that ChatGPT accounts cannot use.

Whether the ChatGPT **Free** plan includes CLI access is still unresolved
(OQ-7): it works on this account, but that does not establish the plan.
"""

from __future__ import annotations

import asyncio
import json
import shutil

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

BINARY = "codex"

CAPABILITIES = BackendCapabilities(
    min_context_tokens=272_000,
    # Measured 2026-10-08, codex-cli 0.161.0: 13,186 input tokens for a one-line
    # prompt. The earlier 18,365 predates this CLI version.
    harness_overhead=13_200,
    native_json_schema=False,
    prompt_caching=True,
    cost_per_run="subscription",
)


def _inner_message(raw: str) -> str:
    """Codex wraps the API's JSON error inside its own message string."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return str(raw)
    if isinstance(data, dict):
        return str((data.get("error") or {}).get("message") or data.get("message") or raw)
    return str(raw)


class CodexCliRunner:
    name = "codex_cli"
    capabilities = CAPABILITIES

    def __init__(self, model: str | None = None, *, timeout: int = 600) -> None:
        self.model = model
        self.timeout = timeout

    async def _ask(self, agent: AgentSpec, prompt: str) -> tuple[str, Usage]:
        if shutil.which(BINARY) is None:
            raise BackendAuthError(
                self.name, "the `codex` CLI on PATH", "install it and run `codex login`"
            )

        command = [
            BINARY,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--ephemeral",
            "-s",
            "read-only",
        ]
        model = agent.model or self.model
        if model:
            command += ["--model", model]
        command.append("-")  # the prompt arrives on stdin

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        payload = f"{agent.system_prompt}\n\n{prompt}".encode()
        try:
            out, err = await asyncio.wait_for(process.communicate(payload), timeout=self.timeout)
        except TimeoutError as exc:
            process.kill()
            raise BackendError(f"{self.name}: no reply within {self.timeout}s") from exc

        text, usage, failure = self._collect(out.decode("utf-8", "replace"))
        stderr = err.decode("utf-8", "replace").strip()

        # A failed turn is reported as an event in the stream, and not always
        # with a non-zero exit. Reading only the exit code and the reply meant
        # a rejected request came back as an empty string, which then surfaced
        # as "reply was not JSON" — blaming the model for what was an auth or
        # model-selection problem.
        if failure and not text:
            raise self._explain(failure)
        if process.returncode != 0 and not text:
            raise self._explain(stderr or f"exited {process.returncode}")

        return text, usage

    def _explain(self, message: str) -> BackendError:
        lowered = message.lower()
        if any(
            marker in lowered
            for marker in ("401", "unauthorized", "token_expired", "expired", "login", "not logged")
        ):
            return BackendAuthError(
                self.name, "a ChatGPT session (run `codex login`)", message[:300]
            )
        return BackendError(f"{self.name}: {message[:400]}")

    @staticmethod
    def _collect(stream: str) -> tuple[str, Usage, str | None]:
        """Read the newline-delimited event stream: `(reply, usage, failure)`.

        The reply is the `item.completed` event whose item type is
        `agent_message`; `turn.completed` carries usage; `error` and
        `turn.failed` carry a failure. Unparseable lines are skipped rather than
        fatal — the stream is a log, and a new event type in a future release
        should not break a working call.
        """
        text, usage, failure = "", Usage(), None
        for line in stream.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = event.get("type")
            if kind == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    text = item.get("text") or item.get("content") or text
            elif kind == "turn.completed":
                counts = event.get("usage") or {}
                usage = Usage(
                    input_tokens=int(counts.get("input_tokens") or 0),
                    output_tokens=int(counts.get("output_tokens") or 0),
                    cache_read_tokens=int(counts.get("cached_input_tokens") or 0),
                    cache_write_tokens=int(counts.get("cache_write_input_tokens") or 0),
                )
            elif kind in ("error", "turn.failed"):
                raw = event.get("message") or (event.get("error") or {}).get("message") or ""
                message = _inner_message(raw)
                # `turn.failed` follows `error` and often carries only a
                # placeholder; keep the first real reason.
                if message and message.strip("{} ") and not failure:
                    failure = message
                failure = failure or "the turn failed"
        return text, usage, failure

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
        credential = "a ChatGPT session (`codex login`)"
        path = shutil.which(BINARY)
        if path is None:
            return HealthReport(self.name, False, "the `codex` CLI on PATH", "not installed")

        # Local and free: it reads the stored credential and makes no model
        # request, so it is safe for a health endpoint that is polled. This used
        # to report "ok" whenever the binary existed, logged in or not.
        try:
            process = await asyncio.create_subprocess_exec(
                BINARY,
                "login",
                "status",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(process.communicate(), timeout=15)
        except (TimeoutError, OSError):
            return HealthReport(self.name, False, credential, "could not read the login status")

        said = (out + err).decode("utf-8", "replace").strip()
        if process.returncode != 0 or "logged in" not in said.lower():
            return HealthReport(
                self.name, False, credential, f"not logged in — run `codex login`. ({said[:120]})"
            )
        return HealthReport(
            self.name, True, credential, said.splitlines()[0] if said else path, model=self.model
        )
