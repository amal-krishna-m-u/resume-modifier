"""The tracing wrapper and its two sinks.

`TracedBackend` wraps any `RunnerBackend`, so one place covers Claude, Codex and
the rest (OQ-10's "wrap the protocol, not each backend").

Two sinks, deliberately different in what they require:

* `LocalLog` — a JSONL file under `traces/` (gitignored). Always available, no
  server, enough to answer "which prompt version, how many tokens, how long".
* `LangfuseSink` — a **self-hosted** Langfuse, opt-in. Traces carry the full
  corpus in the prompt, so the host is checked and a public endpoint is refused:
  PRD §7 lets knowledge-base content leave the machine only in the model call.

The corpus itself (`cache_prefix`) is recorded as a hash and length, not text.
It is identical across a day's calls; storing it every time would bloat the log
and copy the whole career record into every trace for no analytical value.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..runtime.base import AgentResult, AgentSpec, RunnerBackend
from .context import current_scope


def prompt_version(system_prompt: str) -> str:
    """Short content hash of an agent's prompt: the "v1 / v2" an eval compares."""
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:8]


class NotSelfHosted(ValueError):
    pass


def check_self_hosted(host: str) -> str:
    """Refuse anything that is not this machine or a private network.

    Loopback, RFC1918/link-local addresses, `.local`/`.internal`/`.lan` names and
    single-label hostnames (a docker-compose service name) pass. Everything else,
    and Langfuse's managed cloud in particular, does not.
    """
    parsed = urlparse(host if "//" in host else f"http://{host}")
    name = (parsed.hostname or "").lower()
    if not name:
        raise NotSelfHosted(f"{host!r} is not a URL")
    try:
        address = ipaddress.ip_address(name)
        ok = address.is_loopback or address.is_private or address.is_link_local
    except ValueError:
        ok = (
            name == "localhost" or "." not in name or name.endswith((".local", ".internal", ".lan"))
        )
    if not ok or name.endswith("langfuse.com"):
        raise NotSelfHosted(
            f"{name} is not a local or private address. Traces contain your whole "
            "knowledge base; only a self-hosted Langfuse on this machine or your "
            "own network is allowed."
        )
    return host.rstrip("/")


class LocalLog:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def record(self, entry: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


class LangfuseSink:
    """Sends each call to a self-hosted Langfuse as one generation.

    Every call in a run joins one trace, its id derived from the run id, so a
    run reads as a single trace with a generation per agent.
    """

    def __init__(self, host: str, public_key: str, secret_key: str) -> None:
        from langfuse import Langfuse  # optional dependency: `pip install .[tracing]`

        self.host = check_self_hosted(host)
        self.client = Langfuse(public_key=public_key, secret_key=secret_key, host=self.host)

    def trace_id(self, seed: str) -> str:
        return self.client.create_trace_id(seed=seed)

    def record(self, entry: dict[str, Any]) -> None:
        run_id = entry.get("run_id") or "unscoped"
        usage = entry.get("usage") or {}
        with self.client.start_as_current_observation(
            trace_context={"trace_id": self.trace_id(run_id)},
            name=f"{entry.get('kind') or 'call'}:{entry['agent']}",
            as_type="generation",
            model=entry.get("model") or entry["backend"],
            input=entry.get("input"),
            metadata={
                "backend": entry["backend"],
                "prompt_version": entry["prompt_version"],
                "corpus_sha": entry.get("prefix_sha"),
                "repairs": entry.get("repairs", 0),
                "duration_s": entry.get("duration_s"),
                "label": entry.get("label"),
            },
            version=entry["prompt_version"],
        ) as generation:
            generation.update(
                output=entry.get("output"),
                usage_details={
                    "input": usage.get("input_tokens", 0),
                    "output": usage.get("output_tokens", 0),
                    "cache_read_input_tokens": usage.get("cache_read_tokens", 0),
                },
                level="ERROR" if entry.get("error") else "DEFAULT",
                status_message=entry.get("error"),
            )

    def score(self, seed: str, name: str, value: float, comment: str | None = None) -> None:
        self.client.create_score(
            name=name, value=float(value), trace_id=self.trace_id(seed), comment=comment
        )

    def flush(self) -> None:
        self.client.flush()


class TracedBackend:
    """A `RunnerBackend` that records every call, then behaves exactly like it."""

    def __init__(self, inner: RunnerBackend, sinks: list[Any], *, record_content: bool = True):
        self.inner = inner
        self.sinks = sinks
        self.record_content = record_content
        self.name = inner.name
        self.capabilities = inner.capabilities

    async def healthcheck(self):
        return await self.inner.healthcheck()

    async def run_agent(
        self,
        agent: AgentSpec,
        prompt: str,
        *,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        started = time.monotonic()
        error: str | None = None
        result: AgentResult | None = None
        try:
            result = await self.inner.run_agent(
                agent, prompt, cache_prefix=cache_prefix, session_id=session_id
            )
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._emit(agent, prompt, cache_prefix, result, error, time.monotonic() - started)

    def _emit(self, agent, prompt, prefix, result, error, seconds) -> None:
        scope = current_scope()
        usage = vars(result.usage) if result else {}
        entry: dict[str, Any] = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "run_id": scope.get("run_id"),
            "kind": scope.get("kind"),
            "label": scope.get("label"),
            "agent": agent.name,
            "backend": self.name,
            "model": agent.model,
            "prompt_version": prompt_version(agent.system_prompt),
            "prefix_chars": len(prefix or ""),
            "prefix_sha": hashlib.sha256(prefix.encode()).hexdigest()[:12] if prefix else None,
            "duration_s": round(seconds, 2),
            "usage": usage,
            "repairs": result.repairs if result else 0,
            "error": error,
        }
        if self.record_content:
            entry["input"] = prompt
            entry["output"] = (
                result.json
                if result and result.json is not None
                else (result.raw_text if result else None)
            )
        for sink in self.sinks:
            try:
                sink.record(entry)
            except Exception as exc:  # noqa: BLE001 — tracing must never fail a run
                print(f"[tracing] {type(sink).__name__} failed: {exc}")


def build_sinks(config) -> list[Any]:
    obs = config.observability
    sinks: list[Any] = []
    if obs.local_log and config.root:
        sinks.append(LocalLog(Path(config.root) / "traces"))
    if obs.langfuse:
        import os

        public, secret = os.environ.get(obs.public_key_env), os.environ.get(obs.secret_key_env)
        if public and secret:
            try:
                sinks.append(LangfuseSink(obs.host, public, secret))
            except (NotSelfHosted, ImportError) as exc:
                print(f"[tracing] Langfuse disabled: {exc}")
        else:
            print(f"[tracing] Langfuse enabled but {obs.public_key_env}/{obs.secret_key_env} unset")
    return sinks


def wrap(backend: RunnerBackend, config) -> RunnerBackend:
    sinks = build_sinks(config)
    if not sinks:
        return backend
    return TracedBackend(backend, sinks, record_content=config.observability.record_content)
