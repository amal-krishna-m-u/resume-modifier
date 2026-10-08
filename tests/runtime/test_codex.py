"""The Codex backend, against event streams copied from the real CLI (0.161.0).

None of this needs a login or the network. What it pins down is how the runner
behaves when Codex does something other than succeed — which is where a backend
that "worked in the spike" actually breaks.
"""

from __future__ import annotations

import json

import pytest

from resume_tailor.runtime import codex_cli
from resume_tailor.runtime.base import AgentSpec, BackendAuthError, BackendError
from resume_tailor.runtime.codex_cli import CodexCliRunner

SPEC = AgentSpec(name="selector", system_prompt="Select facts. JSON only.")


def event(**data) -> str:
    return json.dumps(data)


SUCCESS = "\n".join(
    [
        event(type="thread.started", thread_id="t1"),
        event(type="turn.started"),
        event(
            type="item.completed", item={"type": "agent_message", "text": '{"ok": true, "n": 3}'}
        ),
        event(
            type="turn.completed",
            usage={
                "input_tokens": 13186,
                "cached_input_tokens": 4480,
                "cache_write_input_tokens": 12,
                "output_tokens": 31,
                "reasoning_output_tokens": 14,
            },
        ),
    ]
)

# Copied from a real failure. The API's JSON error arrives as a STRING inside
# Codex's own `message` field, i.e. encoded twice.
MODEL_MSG = "The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."
MODEL_REJECTED = "\n".join(
    [
        event(type="thread.started", thread_id="t2"),
        event(type="turn.started"),
        event(
            type="error",
            message=json.dumps(
                {
                    "type": "error",
                    "status": 400,
                    "error": {
                        "type": "invalid_request_error",
                        "message": MODEL_MSG,
                    },
                }
            ),
        ),
        event(type="turn.failed", error={"message": "{}"}),
    ]
)

TOKEN_EXPIRED = "\n".join(
    [
        event(type="turn.started"),
        event(
            type="turn.failed",
            error={
                "message": json.dumps(
                    {
                        "error": {
                            "message": "Your authentication token has expired.",
                            "code": "token_expired",
                        }
                    }
                )
            },
        ),
    ]
)


class Proc:
    """Stands in for the subprocess, recording what it was handed."""

    def __init__(self, stdout: str = "", stderr: str = "", code: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, code
        self.stdin: bytes | None = None
        self.killed = False

    async def communicate(self, input: bytes | None = None):
        self.stdin = input
        return self.stdout.encode(), self.stderr.encode()

    def kill(self) -> None:
        self.killed = True


@pytest.fixture
def codex(monkeypatch):
    """Install a stub `codex` and return a handle on what was run."""
    state: dict = {"argv": None, "proc": None, "queue": []}

    async def fake_exec(*argv, **kwargs):
        state["argv"] = list(argv)
        state["kwargs"] = kwargs
        state["proc"] = state["queue"].pop(0) if state["queue"] else Proc(SUCCESS)
        return state["proc"]

    monkeypatch.setattr(codex_cli.shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(codex_cli.asyncio, "create_subprocess_exec", fake_exec)
    return state


# ---------------------------------------------------------------- parsing


def test_a_good_stream_yields_reply_and_usage() -> None:
    text, usage, failure = CodexCliRunner._collect(SUCCESS)
    assert json.loads(text) == {"ok": True, "n": 3}
    assert failure is None
    assert (usage.input_tokens, usage.output_tokens) == (13186, 31)
    assert usage.cache_read_tokens == 4480 and usage.cache_write_tokens == 12


def test_a_failed_turn_yields_the_real_reason_not_a_json_wrapper() -> None:
    _, _, failure = CodexCliRunner._collect(MODEL_REJECTED)
    assert failure == MODEL_MSG


def test_unparseable_lines_are_skipped_not_fatal() -> None:
    """The stream is a log, and a new event type in a future release should not
    break a working call."""
    noisy = "ERROR rmcp::transport: worker quit\n" + SUCCESS + "\nnot json at all\n"
    text, _, failure = CodexCliRunner._collect(noisy)
    assert json.loads(text) == {"ok": True, "n": 3} and failure is None


# ------------------------------------------------------------- invocation


async def test_the_prompt_goes_on_stdin_not_the_command_line(codex) -> None:
    """A single argument is capped at 128 KB on Linux, and a knowledge base
    grows. 400 KB here is a realistic corpus a year from now."""
    big = "x" * 400_000
    await CodexCliRunner().run_agent(SPEC, big)

    assert big.encode() in codex["proc"].stdin
    assert all(len(arg) < 1000 for arg in codex["argv"]), "the prompt leaked into argv"
    assert codex["argv"][-1] == "-"


async def test_calls_are_ephemeral(codex) -> None:
    """Privacy. By default Codex writes a session file per call, and every call
    here carries the whole knowledge base — each run would leave the person's
    complete career record in ~/.codex/sessions."""
    await CodexCliRunner().run_agent(SPEC, "hello")
    assert "--ephemeral" in codex["argv"]


async def test_codex_may_not_write(codex) -> None:
    """It is an agentic CLI and will run shell commands if it decides to. This
    pipeline wants text in and JSON out."""
    await CodexCliRunner().run_agent(SPEC, "hello")
    argv = codex["argv"]
    assert argv[argv.index("-s") + 1] == "read-only"


async def test_the_system_prompt_is_part_of_the_stdin_payload(codex) -> None:
    await CodexCliRunner().run_agent(SPEC, "THE-USER-TURN")
    sent = codex["proc"].stdin.decode()
    assert sent.index("Select facts.") < sent.index("THE-USER-TURN")


async def test_the_persons_model_setting_is_not_discarded(codex) -> None:
    """`--ignore-user-config` drops it, and Codex then falls back to a default
    that ChatGPT accounts cannot use — found by trying it."""
    await CodexCliRunner().run_agent(SPEC, "hello")
    assert "--ignore-user-config" not in codex["argv"]


async def test_an_explicit_model_is_passed_through(codex) -> None:
    await CodexCliRunner(model="gpt-5.5").run_agent(SPEC, "hello")
    assert codex["argv"][codex["argv"].index("--model") + 1] == "gpt-5.5"


# ---------------------------------------------------------------- failures


async def test_a_rejected_request_says_why(codex) -> None:
    """Codex reports failure as events and not always with a non-zero exit. The
    runner used to read only the exit code and the reply, so a rejected request
    returned an empty string and surfaced as "reply was not JSON" — blaming the
    model for what was a model-selection problem."""
    codex["queue"].append(Proc(MODEL_REJECTED, code=0))
    with pytest.raises(BackendError) as exc:
        await CodexCliRunner().run_agent(SPEC, "hello")
    assert "not supported when using Codex" in str(exc.value)
    assert "not JSON" not in str(exc.value)


async def test_an_expired_login_names_the_fix(codex) -> None:
    """AC-R15.3: name the backend and the credential it expected."""
    codex["queue"].append(Proc(TOKEN_EXPIRED, code=1))
    with pytest.raises(BackendAuthError) as exc:
        await CodexCliRunner().run_agent(SPEC, "hello")
    assert exc.value.backend == "codex_cli"
    assert "codex login" in exc.value.credential


async def test_noise_on_stderr_does_not_fail_a_good_reply(codex) -> None:
    """Seen for real: Codex printed 401 errors from its model-list refresh and
    its MCP transport, and the actual request succeeded. Judging by stderr would
    have rejected a working call."""
    noisy = "ERROR codex_models_manager: 401 Unauthorized token_expired\nERROR rmcp: worker quit"
    codex["queue"].append(Proc(SUCCESS, stderr=noisy, code=0))
    result = await CodexCliRunner().run_agent(SPEC, "hello")
    assert result.json == {"ok": True, "n": 3}


async def test_a_crash_with_no_output_reports_stderr(codex) -> None:
    codex["queue"].append(Proc("", stderr="panic: something broke", code=101))
    with pytest.raises(BackendError, match="something broke"):
        await CodexCliRunner().run_agent(SPEC, "hello")


async def test_json_repair_works_through_codex(codex) -> None:
    prose = event(
        type="item.completed", item={"type": "agent_message", "text": "Sure! Here you go."}
    )
    codex["queue"].extend([Proc(prose), Proc(SUCCESS)])
    result = await CodexCliRunner().run_agent(SPEC, "hello")
    assert result.json == {"ok": True, "n": 3} and result.repairs == 1


async def test_usage_is_reported(codex) -> None:
    result = await CodexCliRunner().run_agent(SPEC, "hello")
    assert result.usage.input_tokens == 13186


# ------------------------------------------------------------- healthcheck


async def test_health_reports_a_real_login(codex) -> None:
    codex["queue"].append(Proc("Logged in using ChatGPT\n"))
    report = await CodexCliRunner().healthcheck()
    assert report.ok


async def test_health_reports_not_logged_in(codex) -> None:
    """It used to say "ok" whenever the binary existed, logged in or not."""
    codex["queue"].append(Proc("Not logged in\n", code=1))
    report = await CodexCliRunner().healthcheck()
    assert not report.ok and "codex login" in report.detail


async def test_health_reports_a_missing_binary(monkeypatch) -> None:
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _name: None)
    report = await CodexCliRunner().healthcheck()
    assert not report.ok and "not installed" in report.detail
