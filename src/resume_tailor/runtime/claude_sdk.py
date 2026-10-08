"""The Claude Agent SDK backend — the default (spec-03 §2.2).

OQ-1 is resolved: the SDK works on a Pro/Max subscription session with **no**
`ANTHROPIC_API_KEY` present, verified 2026-10-06 including with every
`CLAUDE_CODE_*` variable stripped. An API key is supported and is not required.

Policy, unchanged by that result: this is one person running their own tool on
their own machine against their own account, which is the "ordinary,
individual usage" the acceptable-use terms name. Distributing a tool that
routes other people's requests through these credentials is not, which is why
the other backends in this package exist.
"""

from __future__ import annotations

import os
from typing import Any

from .base import (
    AgentResult,
    AgentSpec,
    BackendAuthError,
    BackendCapabilities,
    HealthReport,
    Usage,
)
from .json_repair import parse_or_repair
from .live import current_stream

#: Removed explicitly, because `allowed_tools` does **not** restrict anything.
#:
#: Unlisted tools fall through to `permission_mode` and still load their
#: schemas. Measured 2026-10-06: `allowed_tools=[]` alone cost 18,184 input
#: tokens; adding `disallowed_tools` brought the same call to 7,753. The first
#: probe written for this project had exactly that bug.
#: Tokens of reasoning to allow when the live view asks for it.
REASONING_BUDGET = 4000

DISALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Task",
    "TodoWrite",
    "NotebookEdit",
    "BashOutput",
    "KillShell",
    "SlashCommand",
]

#: Claude's window. The harness figure is measured, not estimated — see
#: spec-06 §2.
CAPABILITIES = BackendCapabilities(
    min_context_tokens=200_000,
    harness_overhead=8_000,
    native_json_schema=False,
    prompt_caching=True,
    cost_per_run="subscription",
)


class ClaudeSdkRunner:
    """Runs each agent as one `query()` against the Claude Agent SDK."""

    name = "claude_sdk"
    capabilities = CAPABILITIES

    def __init__(self, model: str | None = None, *, timeout: int = 600) -> None:
        self.model = model
        self.timeout = timeout

    # -- SDK plumbing ------------------------------------------------------

    def _options(self, agent: AgentSpec) -> Any:
        """The lean configuration from spec-06 §2.

        The SDK's defaults are already lean — `system_prompt` defaults to
        `None` and Claude Code's preset is opt-in, which this never passes.
        Two defaults still need overriding, and `setting_sources` is the
        expensive one: left unset it loads the user's MCP servers and costs
        around 10K tokens on every single call.
        """
        from claude_agent_sdk import ClaudeAgentOptions

        options: dict[str, Any] = {
            "system_prompt": agent.system_prompt,
            "setting_sources": [],
            "mcp_servers": {},
            "allowed_tools": [],
            "disallowed_tools": DISALLOWED_TOOLS,
        }
        model = agent.model or self.model
        if model:
            options["model"] = model
        stream = current_stream()
        if stream is not None:
            # Fragments as they are written, for the live view. Harmless when
            # nothing is listening; the final message is still what is returned.
            options["include_partial_messages"] = True
            if stream.want_reasoning:
                options["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": REASONING_BUDGET,
                    # Without this the API returns the block empty.
                    "display": "summarized",
                }
        return ClaudeAgentOptions(**options)

    @staticmethod
    def _usage(raw: Any) -> Usage:
        """Normalise whatever shape the SDK reports usage in.

        Defensive because the field names have moved between SDK versions and
        a missing count should cost accuracy in a report, never a failed run.
        """
        if raw is None:
            return Usage()
        data = raw if isinstance(raw, dict) else getattr(raw, "__dict__", {}) or {}
        return Usage(
            input_tokens=int(data.get("input_tokens") or 0),
            output_tokens=int(data.get("output_tokens") or 0),
            cache_read_tokens=int(data.get("cache_read_input_tokens") or 0),
            cache_write_tokens=int(data.get("cache_creation_input_tokens") or 0),
        )

    async def _ask(self, agent: AgentSpec, prompt: str) -> tuple[str, Usage, str | None]:
        try:
            from claude_agent_sdk import query
        except ImportError as exc:
            raise BackendAuthError(
                self.name,
                "the `claude-agent-sdk` package",
                "install it with `pip install claude-agent-sdk`",
            ) from exc

        chunks: list[str] = []
        usage = Usage()
        session_id: str | None = None

        try:
            stream = current_stream()
            async for message in query(prompt=prompt, options=self._options(agent)):
                if stream is not None and hasattr(message, "event"):
                    self._live(stream, message.event)
                    continue
                for block in getattr(message, "content", None) or []:
                    thought = getattr(block, "thinking", None)
                    if thought and stream is not None and not stream.has_thoughts:
                        stream.thought(thought)
                    text = getattr(block, "text", None)
                    if text:
                        chunks.append(text)
                usage = usage + self._usage(getattr(message, "usage", None))
                session_id = getattr(message, "session_id", None) or session_id
        except Exception as exc:
            raise self._translate(exc) from exc

        return "".join(chunks), usage, session_id

    @staticmethod
    def _live(stream: Any, event: Any) -> None:
        """Forward a partial-message event to the live view."""
        if not isinstance(event, dict) or event.get("type") != "content_block_delta":
            return
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta":
            stream.delta(delta.get("text") or "")
        elif delta.get("type") == "thinking_delta":
            stream.thinking_fragment(delta.get("thinking") or "")

    def _translate(self, exc: Exception) -> Exception:
        """Turn an SDK exception into something the user can act on.

        An expired subscription session and a missing API key both surface as
        opaque process failures; they need different fixes, so the message
        names both paths rather than printing a trace (AC-R15.3).
        """
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()
        if any(word in lowered for word in ("auth", "401", "credential", "unauthor", "login")):
            return BackendAuthError(
                self.name,
                "a Claude subscription session (run `claude login`) or ANTHROPIC_API_KEY",
                text,
            )
        return exc

    # -- interface ---------------------------------------------------------

    async def run_agent(
        self,
        agent: AgentSpec,
        prompt: str,
        *,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        # Corpus first, job description last. The corpus is stable across the
        # Selector and Recall calls and across runs within the cache TTL, so
        # ordering it as the prefix is what makes caching effective (spec-03 §6).
        full = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt

        text, usage, sid = await self._ask(agent, full)

        async def reask(instruction: str) -> str:
            nonlocal usage
            retry, extra, _ = await self._ask(agent, f"{full}\n\n{instruction}")
            usage = usage + extra  # a repair round still costs tokens; count it
            return retry

        value, repairs = await parse_or_repair(text, agent=agent.name, reask=reask)
        return AgentResult(
            agent=agent.name,
            raw_text=text,
            json=value,
            usage=usage,
            session_id=sid or session_id,
            repairs=repairs,
        )

    async def healthcheck(self) -> HealthReport:
        credential = "a Claude subscription session, or ANTHROPIC_API_KEY"
        try:
            import claude_agent_sdk
        except ImportError:
            return HealthReport(
                self.name,
                False,
                credential,
                "claude-agent-sdk is not installed (pip install claude-agent-sdk)",
            )

        return HealthReport(
            self.name,
            True,
            credential,
            "API key present"
            if os.environ.get("ANTHROPIC_API_KEY")
            else "no API key; will use the subscription session (OQ-1)",
            model=self.model,
            version=getattr(claude_agent_sdk, "__version__", None),
        )
