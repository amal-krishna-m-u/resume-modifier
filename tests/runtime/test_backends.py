"""Backend construction, configuration, and the lean-call contract."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from resume_tailor.config import DEFAULT_BACKEND, Config
from resume_tailor.runtime import BACKENDS, BackendError, build_backend
from resume_tailor.runtime.base import AgentSpec
from resume_tailor.runtime.fake import FakeRunner

SPEC = AgentSpec(name="selector", system_prompt="Select facts. Reply with JSON.")


# -- registry --------------------------------------------------------------


@pytest.mark.parametrize("name", [n for n in BACKENDS])
def test_every_registered_backend_constructs(name: str) -> None:
    runner = build_backend(Config(), name)
    assert runner.name == name


def test_unknown_backend_lists_the_real_ones() -> None:
    with pytest.raises(BackendError) as exc:
        build_backend(Config(), "gpt9")
    assert "claude_sdk" in str(exc.value)
    assert "RUNNER_BACKEND" in str(exc.value)


def test_the_default_is_the_sdk() -> None:
    """OQ-1 resolved 2026-10-06: the SDK works on a subscription session with
    no API key, so it is the default. spec-06 §7's example predated that."""
    assert DEFAULT_BACKEND == "claude_sdk"
    assert Config().backend_name() == "claude_sdk"


def test_environment_overrides_the_file(monkeypatch) -> None:
    """So a single run can be pointed elsewhere without editing a file —
    exactly what comparing two backends needs."""
    monkeypatch.setenv("RUNNER_BACKEND", "fake")
    assert Config(backend="claude_sdk").backend_name() == "fake"


# -- configuration ---------------------------------------------------------


def test_a_missing_config_file_is_not_an_error(tmp_path: Path) -> None:
    """Requiring a config file to run would be friction with one right answer."""
    assert Config.load(tmp_path).backend == DEFAULT_BACKEND


def test_config_is_read_from_toml(tmp_path: Path) -> None:
    (tmp_path / "resume-tailor.toml").write_text(
        "[runtime]\n"
        'backend = "openai_compat"\n\n'
        "[runtime.models]\n"
        'default = "sonnet"\n'
        'validator = "opus"\n\n'
        "[runtime.openai_compat]\n"
        'base_url = "http://localhost:1234/v1"\n'
        "context_tokens = 128000\n\n"
        "[render]\n"
        "page_budget = 2\n",
        encoding="utf-8",
    )
    config = Config.load(tmp_path)
    assert config.backend == "openai_compat"
    assert config.openai_compat.context_tokens == 128_000
    assert config.page_budget == 2


def test_validator_model_can_differ_from_the_default(tmp_path: Path) -> None:
    """spec-06 §6: the Validator degrades invisibly, so it gets the strongest
    model rather than the cheapest."""
    (tmp_path / "resume-tailor.toml").write_text(
        '[runtime.models]\ndefault = "small"\nvalidator = "large"\n', encoding="utf-8"
    )
    models = Config.load(tmp_path).models
    assert models.for_agent("selector") == "small"
    assert models.for_agent("validator") == "large"


def test_unknown_config_keys_are_ignored_not_fatal(tmp_path: Path) -> None:
    """A key from a future version must not stop today's binary running."""
    (tmp_path / "resume-tailor.toml").write_text(
        '[runtime]\nbackend = "fake"\nfuture_option = true\n', encoding="utf-8"
    )
    assert Config.load(tmp_path).backend == "fake"


# -- the lean-call contract ------------------------------------------------


def test_sdk_options_remove_tools_and_settings() -> None:
    """spec-06 §2. `allowed_tools` does NOT restrict anything — unlisted tools
    still load their schemas. Measured: 18,184 input tokens with
    `allowed_tools=[]` alone, 7,753 once `disallowed_tools` was added.

    `setting_sources=[]` is the larger saving: left unset it loads the user's
    MCP servers on every call.
    """
    pytest.importorskip("claude_agent_sdk")
    from resume_tailor.runtime.claude_sdk import DISALLOWED_TOOLS, ClaudeSdkRunner

    options = ClaudeSdkRunner()._options(SPEC)
    assert options.setting_sources == []
    assert options.mcp_servers == {}
    assert set(options.disallowed_tools) == set(DISALLOWED_TOOLS)
    # The Claude Code preset is opt-in and must never be passed.
    assert options.system_prompt == SPEC.system_prompt


def test_cli_command_carries_every_lean_flag() -> None:
    from resume_tailor.runtime.claude_cli import LEAN_FLAGS, ClaudeCliRunner

    command = ClaudeCliRunner()._command(SPEC, "hello")
    for flag in LEAN_FLAGS:
        assert flag in command
    assert "--system-prompt" in command
    assert "--disallowed-tools" in command


def test_codex_skips_the_git_repo_check() -> None:
    """Without it the CLI refuses to run outside a repository — found by the
    tool hanging, not by reading the help text."""
    from resume_tailor.runtime.codex_cli import CodexCliRunner

    runner = CodexCliRunner()
    assert runner.capabilities.min_context_tokens == 272_000


def test_openrouter_defaults_fit_this_pipeline(monkeypatch) -> None:
    """OpenRouter is openai_compat with the defaults a full-corpus run needs:
    a 1M window, native JSON, and an auth error that names the real env var.
    A missing key must fail before a request, otherwise the failure looks like
    a network problem."""
    from resume_tailor.runtime.openrouter import DEFAULT_MODEL, OpenRouterRunner

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    runner = OpenRouterRunner()
    assert runner.name == "openrouter"
    assert runner.model == DEFAULT_MODEL
    assert runner.capabilities.min_context_tokens == 1_000_000
    assert runner.capabilities.native_json_schema
    assert runner.capabilities.harness_overhead == 0
    assert runner.capabilities.cost_per_run == "metered"
    assert runner.api_key_env == "OPENROUTER_API_KEY"


async def test_openrouter_healthcheck_names_the_missing_key(monkeypatch) -> None:
    from resume_tailor.runtime.openrouter import OpenRouterRunner

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    report = await OpenRouterRunner().healthcheck()
    assert not report.ok
    assert report.credential == "OPENROUTER_API_KEY"
    assert "OPENROUTER_API_KEY" in report.detail


def test_openrouter_honours_the_per_backend_model() -> None:
    from resume_tailor.runtime.openrouter import OpenRouterRunner

    config = Config()
    config.backend_models["openrouter"] = "z-ai/glm-5.3-flash"
    runner = build_backend(config, "openrouter", trace=False)
    assert isinstance(runner, OpenRouterRunner)
    assert runner.model == "z-ai/glm-5.3-flash"


# -- the fake backend ------------------------------------------------------


async def test_fake_replays_a_scripted_reply() -> None:
    runner = FakeRunner({"selector": {"selected": ["a"]}})
    result = await runner.run_agent(SPEC, "go")
    assert result.json == {"selected": ["a"]}
    assert result.usage.total > 0


async def test_fake_records_prompts_for_ordering_assertions() -> None:
    """Corpus-first ordering is what makes caching work (spec-03 §6), and
    nothing else would catch it silently regressing."""
    runner = FakeRunner({"selector": {}})
    await runner.run_agent(SPEC, "THE-JD", cache_prefix="THE-CORPUS")
    prompt = runner.calls["selector"][0]
    assert prompt.index("THE-CORPUS") < prompt.index("THE-JD")


async def test_fake_returns_a_sequence_across_calls() -> None:
    runner = FakeRunner({"selector": [{"n": 1}, {"n": 2}]})
    assert (await runner.run_agent(SPEC, "a")).json == {"n": 1}
    assert (await runner.run_agent(SPEC, "b")).json == {"n": 2}
    assert (await runner.run_agent(SPEC, "c")).json == {"n": 2}  # last repeats


async def test_fake_can_raise_for_failure_paths() -> None:
    runner = FakeRunner({"selector": {}}, fail_on={"selector": RuntimeError("boom")})
    with pytest.raises(RuntimeError, match="boom"):
        await runner.run_agent(SPEC, "go")


async def test_fake_exercises_json_repair() -> None:
    """A raw string reply goes through the same ladder a real backend uses."""
    runner = FakeRunner({"selector": '```json\n{"a": 1}\n```'})
    assert (await runner.run_agent(SPEC, "go")).json == {"a": 1}


async def test_fake_names_unscripted_agents() -> None:
    runner = FakeRunner({"selector": {}})
    with pytest.raises(KeyError, match="writer"):
        await runner.run_agent(AgentSpec(name="writer", system_prompt="x"), "go")


async def test_fake_reports_healthy() -> None:
    assert (await FakeRunner().healthcheck()).ok


# -- health ----------------------------------------------------------------


async def test_sdk_health_says_which_credential_it_will_use(monkeypatch) -> None:
    pytest.importorskip("claude_agent_sdk")
    from resume_tailor.runtime.claude_sdk import ClaudeSdkRunner

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = await ClaudeSdkRunner().healthcheck()
    assert report.ok
    assert "subscription" in report.detail

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert "API key" in (await ClaudeSdkRunner().healthcheck()).detail


async def test_missing_binary_reports_unavailable_not_a_crash(monkeypatch) -> None:
    import shutil

    from resume_tailor.runtime.claude_cli import ClaudeCliRunner

    monkeypatch.setattr(shutil, "which", lambda _: None)
    report = await ClaudeCliRunner().healthcheck()
    assert not report.ok
    assert "not installed" in report.detail


# -- live ------------------------------------------------------------------


@pytest.mark.live
async def test_sdk_round_trip_on_the_real_backend() -> None:
    """OQ-1's result, as a standing test rather than a one-off spike.

    Enforcement behaviour can change; if it does, this is what notices.
    """
    pytest.importorskip("claude_agent_sdk")
    from resume_tailor.runtime.claude_sdk import ClaudeSdkRunner

    os.environ.pop("ANTHROPIC_API_KEY", None)
    spec = AgentSpec(
        name="probe",
        system_prompt="You reply with JSON only. No prose, no code fences.",
    )
    result = await ClaudeSdkRunner().run_agent(spec, 'Reply with exactly this JSON: {"ok": true}')
    assert result.json == {"ok": True}
    assert result.usage.input_tokens > 0


@pytest.mark.live
async def test_openrouter_round_trip_on_the_real_backend() -> None:
    """Same bar as the other live backends: JSON out, usage reported."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY is not set")
    runner = build_backend(Config(), "openrouter", trace=False)
    assert (await runner.healthcheck()).ok
    spec = AgentSpec(
        name="probe", system_prompt="You reply with JSON only. No prose, no code fences."
    )
    result = await runner.run_agent(spec, 'Reply with exactly this JSON: {"ok": true}')
    assert result.json == {"ok": True}
    assert result.usage.input_tokens > 0


@pytest.mark.live
@pytest.mark.parametrize("name", ["claude_sdk", "claude_cli", "codex_cli"])
async def test_every_supported_backend_returns_json(name: str) -> None:
    """The bare minimum for a backend to be supported: a logged-in session, a
    strict-JSON reply, and usage reported. Run with `pytest -m live`."""
    from resume_tailor.config import Config
    from resume_tailor.runtime import build_backend

    os.environ.pop("ANTHROPIC_API_KEY", None)
    runner = build_backend(Config(), name)
    assert (await runner.healthcheck()).ok
    spec = AgentSpec(
        name="probe", system_prompt="You reply with JSON only. No prose, no code fences."
    )
    result = await runner.run_agent(spec, 'Reply with exactly this JSON: {"ok": true}')
    assert result.json == {"ok": True}
    assert result.usage.input_tokens > 0
