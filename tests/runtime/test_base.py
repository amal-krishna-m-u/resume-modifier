"""The backend interface and the context gate (spec-03 §2, spec-06 §4)."""

from __future__ import annotations

import pytest

from resume_tailor.runtime.base import (
    AgentSpec,
    BackendAuthError,
    BackendCapabilities,
    ContextExceeded,
    HealthReport,
    RunnerBackend,
    Usage,
)

CLAUDE = BackendCapabilities(
    min_context_tokens=200_000,
    harness_overhead=8_000,
    native_json_schema=False,
    prompt_caching=True,
    cost_per_run="subscription",
)

SMALL = BackendCapabilities(
    min_context_tokens=8_000,
    harness_overhead=500,
    native_json_schema=True,
    prompt_caching=False,
    cost_per_run="free",
)


# -- the context gate ------------------------------------------------------


def test_a_corpus_that_fits_is_allowed() -> None:
    CLAUDE.assert_corpus_fits("claude_sdk", corpus_tokens=18_000)


def test_a_corpus_that_does_not_fit_is_refused() -> None:
    """spec-06 §4: refuse to start, never chunk.

    Chunked selection silently reintroduces the lossy retrieval AC-R11.3
    forbids, and the omissions are invisible. A loud refusal is correct;
    degrading gracefully here is not graceful.
    """
    with pytest.raises(ContextExceeded) as exc:
        SMALL.assert_corpus_fits("tiny_local", corpus_tokens=50_000)
    assert "tiny_local" in str(exc.value)


def test_the_refusal_names_the_shortfall() -> None:
    """An error that says only "too big" leaves the user guessing at what
    would fit."""
    with pytest.raises(ContextExceeded) as exc:
        SMALL.assert_corpus_fits("tiny_local", corpus_tokens=50_000)
    message = str(exc.value)
    assert "50,000" in message  # the corpus
    assert "8,000" in message  # the window
    assert "Short by" in message


def test_the_refusal_says_splitting_is_not_the_answer() -> None:
    """The obvious next thought is "chunk it", and that is the failure mode."""
    with pytest.raises(ContextExceeded) as exc:
        SMALL.assert_corpus_fits("tiny_local", corpus_tokens=50_000)
    assert "cannot be worked around by splitting" in str(exc.value)


def test_headroom_is_counted() -> None:
    """A corpus that exactly fills the window leaves no room for the reply."""
    caps = BackendCapabilities(10_000, 0, False, False, "free")
    with pytest.raises(ContextExceeded):
        caps.assert_corpus_fits("x", corpus_tokens=9_999)
    caps.assert_corpus_fits("x", corpus_tokens=1_000, headroom=500)


def test_overhead_is_counted() -> None:
    """A small corpus can still fail on a backend with a heavy harness.

    9,000 of overhead against a 10,000 window leaves 1,000: a corpus of 1,500
    does not fit even though it is a seventh of the nominal window.
    """
    caps = BackendCapabilities(10_000, 9_000, False, False, "free")
    caps.assert_corpus_fits("x", corpus_tokens=500, headroom=100)  # 9,600 — fits
    with pytest.raises(ContextExceeded):
        caps.assert_corpus_fits("x", corpus_tokens=1_500, headroom=100)  # 10,600


# -- auth errors are actionable -------------------------------------------


def test_auth_error_names_backend_and_credential() -> None:
    """AC-R15.3. An expired OAuth session and a missing API key are identical
    in a traceback and need completely different fixes."""
    error = BackendAuthError("claude_sdk", "ANTHROPIC_API_KEY", "401 from the API")
    assert "claude_sdk" in str(error)
    assert "ANTHROPIC_API_KEY" in str(error)
    assert error.backend == "claude_sdk"
    assert error.credential == "ANTHROPIC_API_KEY"


# -- usage accounting -----------------------------------------------------


def test_usage_adds() -> None:
    total = Usage(10, 5, 2, 1) + Usage(20, 7, 3, 0)
    assert (total.input_tokens, total.output_tokens) == (30, 12)
    assert (total.cache_read_tokens, total.cache_write_tokens) == (5, 1)


def test_usage_total_excludes_cache_counts() -> None:
    """Cache reads are already inside `input_tokens`; adding them would
    double-count and overstate every run."""
    assert Usage(100, 50, cache_read_tokens=90).total == 150


def test_usage_starts_empty() -> None:
    assert Usage().total == 0


# -- shape ----------------------------------------------------------------


def test_agent_spec_defaults_are_conservative() -> None:
    spec = AgentSpec(name="selector", system_prompt="...")
    assert spec.model is None  # backend's default
    assert spec.requires_strong_model is False


def test_health_report_reads_as_a_sentence() -> None:
    report = HealthReport("claude_sdk", True, "subscription session", "no key present")
    assert str(report) == "claude_sdk: ok (auth: subscription session) — no key present"


def test_every_backend_satisfies_the_protocol() -> None:
    """The point of the protocol is that the orchestrator sees only this."""
    from resume_tailor.runtime.claude_cli import ClaudeCliRunner
    from resume_tailor.runtime.claude_sdk import ClaudeSdkRunner
    from resume_tailor.runtime.codex_cli import CodexCliRunner
    from resume_tailor.runtime.fake import FakeRunner
    from resume_tailor.runtime.openai_compat import OpenAICompatRunner
    from resume_tailor.runtime.openrouter import OpenRouterRunner

    for runner in (
        ClaudeSdkRunner(),
        ClaudeCliRunner(),
        CodexCliRunner(),
        OpenRouterRunner(),
        OpenAICompatRunner(),
        FakeRunner(),
    ):
        assert isinstance(runner, RunnerBackend), runner.name
        assert runner.capabilities.min_context_tokens > 0
