"""Background start/stop for the local web interface.

`rt serve` stays in the foreground. `rt start` detaches it so the same
command works from any directory; `rt stop` closes that process. The pid
file lives under the project's `.cache/`, next to everything else that is
machine-local and gitignored.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PID_NAME = "server.pid"
LOG_NAME = "server.log"
#: Local name for the UI. Add `127.0.0.1 rs.local` to /etc/hosts yourself.
ALIAS_HOST = "rs.local"


@dataclass(frozen=True)
class ServerState:
    running: bool
    pid: int | None = None
    port: int | None = None
    detail: str = ""


def alias_resolves(host: str = ALIAS_HOST) -> bool:
    try:
        return any(info[4][0] in {"127.0.0.1", "::1"} for info in socket.getaddrinfo(host, None))
    except OSError:
        return False


def public_url(port: int | None, host: str = ALIAS_HOST) -> str:
    """http://rs.local when the alias points here; otherwise 127.0.0.1.

    Port 80 is omitted so the address is just `http://rs.local`.
    """
    name = host if alias_resolves(host) else "127.0.0.1"
    if port in (None, 80):
        return f"http://{name}"
    return f"http://{name}:{port}"


def open_browser(url: str) -> None:
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen(
        [opener, url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def pid_file(root: Path) -> Path:
    return root / ".cache" / PID_NAME


def log_file(root: Path) -> Path:
    return root / ".cache" / LOG_NAME


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_state(root: Path) -> ServerState:
    path = pid_file(root)
    if not path.is_file():
        return ServerState(False, detail="not running")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        pid = int(lines[0])
        port = int(lines[1]) if len(lines) > 1 else None
    except (ValueError, OSError):
        return ServerState(False, detail="stale pid file")
    if not _alive(pid):
        return ServerState(False, pid=pid, port=port, detail="stale pid file")
    return ServerState(True, pid=pid, port=port, detail="running")


def write_state(root: Path, pid: int, port: int) -> Path:
    path = pid_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n{port}\n", encoding="utf-8")
    return path


def start(root: Path, port: int, *, argv0: str | None = None) -> ServerState:
    """Detach `rt serve` and record its pid. Idempotent if already running."""
    current = read_state(root)
    if current.running:
        return current

    cache = root / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    log = log_file(root)
    command = [argv0 or sys.argv[0], "serve", "--root", str(root), "--port", str(port)]
    handle = log.open("ab")
    try:
        proc = subprocess.Popen(
            command,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "RESUME_TAILOR_ROOT": str(root)},
        )
    except OSError as exc:
        handle.close()
        return ServerState(False, port=port, detail=str(exc))

    time.sleep(0.3)
    if proc.poll() is not None:
        handle.close()
        tail = log.read_text(encoding="utf-8", errors="replace")[-500:].strip()
        return ServerState(
            False,
            pid=proc.pid,
            port=port,
            detail=tail or f"serve exited {proc.returncode}",
        )
    write_state(root, proc.pid, port)
    return ServerState(True, pid=proc.pid, port=port, detail="started")


def stop(root: Path, *, timeout: float = 5.0) -> ServerState:
    """SIGTERM the detached serve process; SIGKILL if it ignores that."""
    current = read_state(root)
    path = pid_file(root)
    if not current.running:
        path.unlink(missing_ok=True)
        return ServerState(False, detail="not running")
    assert current.pid is not None
    try:
        os.kill(current.pid, signal.SIGTERM)
    except ProcessLookupError:
        path.unlink(missing_ok=True)
        return ServerState(False, pid=current.pid, port=current.port, detail="not running")

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _alive(current.pid):
            path.unlink(missing_ok=True)
            return ServerState(False, pid=current.pid, port=current.port, detail="stopped")
        time.sleep(0.05)

    with contextlib.suppress(ProcessLookupError):
        os.kill(current.pid, signal.SIGKILL)
    path.unlink(missing_ok=True)
    return ServerState(False, pid=current.pid, port=current.port, detail="killed")
