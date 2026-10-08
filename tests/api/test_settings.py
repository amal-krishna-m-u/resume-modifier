"""Choosing the backend from the UI (the Settings screen)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resume_tailor.api.app import create_app
from resume_tailor.config import Config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("RUNNER_BACKEND", raising=False)
    (tmp_path / "kb").mkdir()
    with TestClient(create_app(tmp_path)) as client:
        client.root = tmp_path
        yield client


def test_defaults_list_every_real_backend(client) -> None:
    body = client.get("/api/settings").json()
    assert body["backend"] == "claude_sdk"
    assert {b["name"] for b in body["backends"]} >= {"claude_sdk", "claude_cli", "codex_cli"}
    assert "fake" not in {b["name"] for b in body["backends"]}


def test_switching_persists_and_reloads(client) -> None:
    r = client.put(
        "/api/settings", json={"backend": "codex_cli", "models": {"codex_cli": "gpt-5.5"}}
    )
    assert r.status_code == 200 and r.json()["backend"] == "codex_cli"
    reloaded = Config.load(client.root)
    assert reloaded.backend == "codex_cli"
    assert reloaded.model_for("codex_cli") == "gpt-5.5"


def test_a_claude_model_never_leaks_to_codex(client) -> None:
    """The reason models are per backend: 'opus' means nothing to Codex."""
    client.put("/api/settings", json={"backend": "claude_sdk", "models": {"claude_sdk": "opus"}})
    config = Config.load(client.root)
    assert config.model_for("claude_sdk") == "opus"
    assert config.model_for("codex_cli") is None


def test_unknown_backend_is_refused_with_a_remedy(client) -> None:
    r = client.put("/api/settings", json={"backend": "gemini"})
    assert r.status_code >= 400 and "claude_sdk" in r.json()["remedy"]
    assert Config.load(client.root).backend == "claude_sdk"


def test_the_environment_override_is_reported(client, monkeypatch) -> None:
    monkeypatch.setenv("RUNNER_BACKEND", "codex_cli")
    body = client.get("/api/settings").json()
    assert body["env_override"] and body["effective_backend"] == "codex_cli"


def test_refused_while_a_run_is_active(client) -> None:
    client.app.state.context.active_runs.add("some-run")
    r = client.put("/api/settings", json={"backend": "codex_cli"})
    assert r.status_code == 409


def test_testing_a_backend_does_not_save_it(client) -> None:
    r = client.post("/api/settings/test", json={"backend": "codex_cli"})
    assert r.status_code == 200 and "ok" in r.json() and r.json()["login"] == "codex login"
    assert Config.load(client.root).backend == "claude_sdk"


def test_serve_root_is_honoured(tmp_path, monkeypatch) -> None:
    """`rt serve --root X` once printed X and then served the working directory."""
    (tmp_path / "kb").mkdir()
    monkeypatch.setenv("RESUME_TAILOR_ROOT", str(tmp_path))
    assert create_app().state.context.root == tmp_path.resolve()


def test_observability_status_reports_local_log_and_refuses_public_hosts(client) -> None:
    body = client.get("/api/observability").json()
    assert body["local_log"] and body["langfuse"]["enabled"] is False
    assert body["summary"] == [] and body["evals"] == []

    cfg = client.app.state.context.config
    cfg.observability.host = "https://cloud.langfuse.com"
    assert "not a local" in client.get("/api/observability").json()["langfuse"]["refused"]
