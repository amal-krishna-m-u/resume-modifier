"""Tracing (OQ-10): what is recorded, where it may go, and that it never breaks a run."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from resume_tailor.config import Config, ObservabilityConfig
from resume_tailor.observability import (
    LangfuseSink,
    LocalLog,
    TracedBackend,
    check_self_hosted,
    prompt_version,
    scope,
)
from resume_tailor.observability.summary import read_entries, summarise
from resume_tailor.observability.tracing import NotSelfHosted
from resume_tailor.runtime import build_backend
from resume_tailor.runtime.base import AgentSpec, BackendError
from resume_tailor.runtime.fake import FakeRunner

SPEC = AgentSpec(name="selector", system_prompt="Select facts.", model="m1")


def traced(tmp_path: Path, runner=None, **kwargs):
    sink = LocalLog(tmp_path / "traces")
    return TracedBackend(runner or FakeRunner({"selector": {"ok": 1}}), [sink], **kwargs), tmp_path


# -- the host guard ---------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.1.20:3000",
        "http://10.0.0.5",
        "http://langfuse-web:3000",  # a docker-compose service name
        "http://box.local:3000",
    ],
)
def test_self_hosted_addresses_are_allowed(host: str) -> None:
    assert check_self_hosted(host)


@pytest.mark.parametrize(
    "host",
    [
        "https://cloud.langfuse.com",
        "https://us.cloud.langfuse.com",
        "https://example.com",
        "http://8.8.8.8:3000",
    ],
)
def test_anything_public_is_refused(host: str) -> None:
    """Traces carry the whole knowledge base in the prompt (PRD §7)."""
    with pytest.raises(NotSelfHosted):
        check_self_hosted(host)


# -- what is recorded ----------------------------------------------------------


async def test_a_call_is_recorded_with_its_prompt_version_and_scope(tmp_path) -> None:
    backend, root = traced(tmp_path)
    with scope(run_id="run-1", kind="tailor"):
        await backend.run_agent(SPEC, "the user turn", cache_prefix="THE CORPUS")

    (entry,) = read_entries(root)
    assert entry["run_id"] == "run-1" and entry["kind"] == "tailor"
    assert entry["agent"] == "selector" and entry["model"] == "m1"
    assert entry["prompt_version"] == prompt_version("Select facts.")
    assert entry["usage"]["input_tokens"] == 100
    assert entry["input"] == "the user turn" and entry["output"] == {"ok": 1}


async def test_the_corpus_is_hashed_not_copied(tmp_path) -> None:
    """It is identical across a day's calls; storing it each time would put the
    whole career record in every trace for no analytical value."""
    backend, root = traced(tmp_path)
    await backend.run_agent(SPEC, "x", cache_prefix="EVERY EMPLOYER AND DATE")
    text = (next((root / "traces").glob("*.jsonl"))).read_text()
    assert "EVERY EMPLOYER" not in text
    assert read_entries(root)[0]["prefix_chars"] == len("EVERY EMPLOYER AND DATE")


async def test_content_can_be_switched_off(tmp_path) -> None:
    backend, root = traced(tmp_path, record_content=False)
    await backend.run_agent(SPEC, "private posting text")
    (entry,) = read_entries(root)
    assert "input" not in entry and "output" not in entry
    assert entry["usage"]["input_tokens"] == 100


async def test_a_failure_is_recorded_and_still_raised(tmp_path) -> None:
    runner = FakeRunner({}, fail_on={"selector": BackendError("codex_cli: model not supported")})
    backend, root = traced(tmp_path, runner)
    with pytest.raises(BackendError):
        await backend.run_agent(SPEC, "x")
    assert "model not supported" in read_entries(root)[0]["error"]


async def test_a_broken_sink_never_fails_the_run(tmp_path) -> None:
    class Broken:
        def record(self, entry):
            raise RuntimeError("disk full")

    backend = TracedBackend(FakeRunner({"selector": {"ok": 1}}), [Broken()])
    result = await backend.run_agent(SPEC, "x")
    assert result.json == {"ok": 1}


def test_the_wrapper_is_transparent_about_the_backend(tmp_path) -> None:
    inner = FakeRunner()
    backend, _ = traced(tmp_path, inner)
    assert backend.name == inner.name and backend.capabilities is inner.capabilities


def test_build_backend_always_wraps_unless_told_not_to(tmp_path) -> None:
    """The live view needs the wrapper even with every log sink off."""
    off = Config(root=tmp_path, observability=ObservabilityConfig(local_log=False))
    assert isinstance(build_backend(off, "fake"), TracedBackend)
    assert not isinstance(build_backend(off, "fake", trace=False), TracedBackend)


async def test_concurrent_agents_both_see_the_run(tmp_path) -> None:
    import asyncio

    backend, root = traced(tmp_path, FakeRunner({"selector": {}, "recall": {}}))
    with scope(run_id="r"):
        await asyncio.gather(
            asyncio.create_task(backend.run_agent(SPEC, "a")),
            asyncio.create_task(
                backend.run_agent(AgentSpec(name="recall", system_prompt="p"), "b")
            ),
        )
    assert {e["run_id"] for e in read_entries(root)} == {"r"}


# -- reading it back --------------------------------------------------------------


async def test_summary_groups_by_agent_and_prompt_version(tmp_path) -> None:
    backend, root = traced(tmp_path)
    await backend.run_agent(SPEC, "x")
    await backend.run_agent(SPEC, "y")
    await backend.run_agent(AgentSpec(name="selector", system_prompt="Select better."), "z")
    rows = summarise(read_entries(root))
    assert sorted(r["calls"] for r in rows) == [1, 2]
    assert len({r["prompt_version"] for r in rows}) == 2


def test_a_torn_last_line_does_not_hide_the_rest(tmp_path) -> None:
    directory = tmp_path / "traces"
    directory.mkdir()
    good = json.dumps({"agent": "a", "prompt_version": "v", "backend": "b"})
    (directory / "2026-10-09.jsonl").write_text(good + '\n{"agent": "tr')
    assert len(read_entries(tmp_path)) == 1


# -- config -------------------------------------------------------------------------


def test_observability_settings_round_trip(tmp_path) -> None:
    config = Config(root=tmp_path)
    config.observability = ObservabilityConfig(langfuse=True, host="http://langfuse-web:3000")
    config.save(tmp_path)
    loaded = Config.load(tmp_path)
    assert loaded.observability.langfuse and loaded.observability.host.endswith(":3000")
    assert loaded.observability.local_log is True


# -- the Langfuse exporter, against a stub server -------------------------------------


class _Collector(BaseHTTPRequestHandler):
    hits: list[tuple[str, int]] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        self.rfile.read(length)
        type(self).hits.append((self.path, length))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_):
        pass


def test_a_generation_is_exported_to_the_otlp_endpoint() -> None:
    """No Langfuse server is needed to prove the SDK is wired correctly: Langfuse
    ingests OpenTelemetry at /api/public/otel/v1/traces, so a stub that records
    the POST shows a generation really left the process."""
    _Collector.hits = []
    server = HTTPServer(("127.0.0.1", 0), _Collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        sink = LangfuseSink(f"http://127.0.0.1:{server.server_port}", "pk-test", "sk-test")
        sink.record(
            {
                "agent": "selector",
                "backend": "fake",
                "model": "m1",
                "prompt_version": "abc12345",
                "run_id": "run-1",
                "kind": "tailor",
                "input": "posting",
                "output": {"ok": 1},
                "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 2},
                "duration_s": 1.2,
            }
        )
        sink.flush()
    finally:
        server.shutdown()
    paths = [p for p, size in _Collector.hits if size > 0]
    assert any(p.endswith("/api/public/otel/v1/traces") for p in paths), _Collector.hits


def test_a_public_host_is_refused_before_anything_is_sent() -> None:
    with pytest.raises(NotSelfHosted):
        LangfuseSink("https://cloud.langfuse.com", "pk", "sk")


# -- the live view ------------------------------------------------------------------


@pytest.fixture
def published():
    from resume_tailor.observability import set_publisher

    events: list[tuple[str, str, dict]] = []
    set_publisher(lambda key, event, data: events.append((key, event, data)))
    yield events
    set_publisher(None)


async def test_a_call_publishes_start_and_end_to_the_live_view(tmp_path, published) -> None:
    backend, _ = traced(tmp_path)
    with scope(run_id="run-9", kind="tailor"):
        await backend.run_agent(SPEC, "the posting", cache_prefix="CORPUS")
    kinds = [event for _, event, _ in published]
    assert kinds[0] == "call_start" and kinds[-1] == "call_end"
    start, end = published[0][2], published[-1][2]
    assert start["agent"] == "selector" and start["input"] == "the posting"
    assert "CORPUS" not in json.dumps(published), "the corpus must never be streamed"
    assert end["output"] == {"ok": 1} and end["usage"]["input_tokens"] == 100
    assert start["id"] == end["id"] and published[0][0] == "run-9"


async def test_a_failed_call_ends_with_its_error(tmp_path, published) -> None:
    runner = FakeRunner({}, fail_on={"selector": BackendError("boom")})
    backend, _ = traced(tmp_path, runner)
    with scope(run_id="r"), pytest.raises(BackendError):
        await backend.run_agent(SPEC, "x")
    assert "boom" in published[-1][2]["error"]


async def test_calls_outside_a_run_are_not_published(tmp_path, published) -> None:
    backend, _ = traced(tmp_path)
    await backend.run_agent(SPEC, "x")
    assert published == []


async def test_a_dead_listener_cannot_fail_a_call(tmp_path) -> None:
    from resume_tailor.observability import set_publisher

    def broken(*_):
        raise RuntimeError("socket closed")

    set_publisher(broken)
    try:
        backend, _ = traced(tmp_path)
        with scope(run_id="r"):
            result = await backend.run_agent(SPEC, "x")
        assert result.json == {"ok": 1}
    finally:
        set_publisher(None)


async def test_reasoning_is_kept_in_the_log_and_the_final_event(tmp_path, published) -> None:
    class Thinker(FakeRunner):
        async def run_agent(self, agent, prompt, **kw):
            from resume_tailor.observability import current_stream

            current_stream().thought("RQ1 matches the ingestion fact")
            current_stream().thinking_fragment("and RQ2 needs the trading engine")
            return await super().run_agent(agent, prompt, **kw)

    backend, root = traced(tmp_path, Thinker({"selector": {"ok": 1}}), show_reasoning=True)
    with scope(run_id="r"):
        await backend.run_agent(SPEC, "x")
    assert read_entries(root)[0]["reasoning"] == [
        "RQ1 matches the ingestion fact",
        "and RQ2 needs the trading engine",
    ]
    assert any(event == "reasoning" for _, event, _ in published)


def test_claude_stream_events_become_output_and_thinking() -> None:
    from resume_tailor.runtime.claude_sdk import ClaudeSdkRunner
    from resume_tailor.runtime.live import CallStream

    with CallStream("r", "selector") as stream:
        ClaudeSdkRunner._live(
            stream, {"type": "content_block_delta", "delta": {"type": "text_delta", "text": '{"a"'}}
        )
        ClaudeSdkRunner._live(
            stream,
            {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hmm"}},
        )
        ClaudeSdkRunner._live(stream, {"type": "message_start"})  # ignored
    stream.close()
    assert stream.output == '{"a"' and stream.reasoning == ["hmm"]


def test_claude_reasoning_uses_the_summarised_thinking_config() -> None:
    """`max_thinking_tokens` returned no thinking at all in testing; the explicit
    config with `display: summarized` is what makes the block carry text."""
    from resume_tailor.runtime.claude_sdk import ClaudeSdkRunner
    from resume_tailor.runtime.live import CallStream

    runner = ClaudeSdkRunner()
    assert getattr(runner._options(SPEC), "thinking", None) is None
    with CallStream("r", "selector", want_reasoning=True):
        thinking = runner._options(SPEC).thinking
    assert thinking["type"] == "enabled" and thinking["display"] == "summarized"


def test_streamed_and_final_thinking_are_not_both_recorded() -> None:
    from resume_tailor.runtime.live import CallStream

    stream = CallStream("r", "a")
    assert not stream.has_thoughts
    stream.thinking_fragment("working it out")
    assert stream.has_thoughts
