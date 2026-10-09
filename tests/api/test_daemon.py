"""Background start/stop must not depend on the working directory, and must
not leave a pid file pointing at a dead process."""

from __future__ import annotations

from pathlib import Path

from resume_tailor.api import daemon


class FakeProc:
    def __init__(self, pid: int = 4242, alive: bool = True) -> None:
        self.pid = pid
        self._alive = alive

    def poll(self) -> int | None:
        return None if self._alive else 1


def test_start_records_pid_and_port(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(daemon.time, "sleep", lambda _n: None)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: FakeProc())
    state = daemon.start(tmp_path, 8000, argv0="/tmp/rt")
    assert state.running and state.pid == 4242 and state.port == 8000
    assert daemon.pid_file(tmp_path).read_text(encoding="utf-8") == "4242\n8000\n"


def test_start_is_idempotent_when_already_running(tmp_path: Path, monkeypatch) -> None:
    daemon.write_state(tmp_path, 4242, 8000)
    monkeypatch.setattr(daemon, "_alive", lambda pid: pid == 4242)

    def boom(*_a, **_k):
        raise AssertionError("must not spawn a second server")

    monkeypatch.setattr(daemon.subprocess, "Popen", boom)
    state = daemon.start(tmp_path, 9000, argv0="/tmp/rt")
    assert state.running and state.port == 8000


def test_start_reports_a_child_that_exits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(daemon.time, "sleep", lambda _n: None)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: FakeProc(alive=False))
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "server.log").write_text("boom\n", encoding="utf-8")
    state = daemon.start(tmp_path, 8000, argv0="/tmp/rt")
    assert not state.running
    assert "boom" in state.detail
    assert not daemon.pid_file(tmp_path).exists()


def test_stop_sends_sigterm_and_removes_the_pid_file(tmp_path: Path, monkeypatch) -> None:
    daemon.write_state(tmp_path, 4242, 8000)
    sent: list[tuple[int, int]] = []
    alive = True

    def _alive(_pid: int) -> bool:
        return alive

    def kill(pid: int, sig: int) -> None:
        nonlocal alive
        sent.append((pid, sig))
        alive = False

    monkeypatch.setattr(daemon, "_alive", _alive)
    monkeypatch.setattr(daemon.os, "kill", kill)
    state = daemon.stop(tmp_path)
    assert not state.running and state.detail == "stopped"
    assert sent and sent[0][0] == 4242
    assert not daemon.pid_file(tmp_path).exists()


def test_stop_when_nothing_is_running(tmp_path: Path) -> None:
    assert daemon.stop(tmp_path).detail == "not running"


def test_public_url_uses_rs_local_when_it_points_here(monkeypatch) -> None:
    monkeypatch.setattr(daemon, "alias_resolves", lambda host="rs.local": True)
    assert daemon.public_url(8000) == "http://rs.local:8000"
    assert daemon.public_url(80) == "http://rs.local"


def test_public_url_falls_back_to_loopback(monkeypatch) -> None:
    monkeypatch.setattr(daemon, "alias_resolves", lambda host="rs.local": False)
    assert daemon.public_url(8000) == "http://127.0.0.1:8000"


def test_stale_pid_file_is_not_running(tmp_path: Path, monkeypatch) -> None:
    daemon.write_state(tmp_path, 1, 8000)
    monkeypatch.setattr(daemon, "_alive", lambda _pid: False)
    state = daemon.read_state(tmp_path)
    assert not state.running
    assert state.detail == "stale pid file"
