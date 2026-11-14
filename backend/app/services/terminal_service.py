"""Interactive terminal sessions for the workspace drawer.

A real shell on a pseudo-terminal, started in the conversation's working
directory, so tools that check for a terminal (colours, prompts, `less`,
REPLs) behave as they would in your own terminal.

Transport is plain HTTP (start / poll output / send input / resize), not a
WebSocket. Starlette's HTTP middleware doesn't run for WebSocket routes, so
a WebSocket endpoint would sit outside Zenith's network guard, shared-secret
and passcode checks. HTTP keeps every request behind those gates.

This is a direct user action, like the code panel's Run button: it is not
an agent tool, not approval-gated, and not sandboxed. It runs as your user.

POSIX only (Linux, macOS). Windows has no `pty` module; `available()`
reports that so the UI can say so instead of failing.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import signal
import struct
import sys
import threading
import time
from dataclasses import dataclass, field

MAX_BUFFER = 512 * 1024      # bytes of scrollback kept per session
IDLE_TIMEOUT = 15 * 60       # seconds without a poll before a session is killed
MAX_SESSIONS = 8


def available() -> bool:
    return sys.platform != "win32"


@dataclass
class Session:
    id: str
    conversation_id: str
    pid: int
    fd: int
    cwd: str
    started: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    buffer: bytearray = field(default_factory=bytearray)
    offset: int = 0            # absolute position of buffer[0] in the output stream
    alive: bool = True
    exit_code: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    changed: threading.Condition | None = None

    @property
    def end(self) -> int:
        return self.offset + len(self.buffer)


_sessions: dict[str, Session] = {}
_registry_lock = threading.Lock()


def _shell() -> list[str]:
    shell = os.environ.get("SHELL") or "/bin/bash"
    if not os.path.exists(shell):
        shell = "/bin/sh"
    return [shell, "-i"]


def _reader(s: Session) -> None:
    """Background thread: copy pty output into the session buffer."""
    while True:
        try:
            chunk = os.read(s.fd, 65536)
        except OSError:
            chunk = b""
        if not chunk:
            break
        with s.lock:
            s.buffer.extend(chunk)
            overflow = len(s.buffer) - MAX_BUFFER
            if overflow > 0:
                del s.buffer[:overflow]
                s.offset += overflow
        assert s.changed is not None
        with s.changed:
            s.changed.notify_all()
    try:
        _, status = os.waitpid(s.pid, 0)
        s.exit_code = os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        pass
    s.alive = False
    try:
        os.close(s.fd)
    except OSError:
        pass
    assert s.changed is not None
    with s.changed:
        s.changed.notify_all()


def start(conversation_id: str, cwd: str, cols: int = 100, rows: int = 30) -> Session:
    """Start a shell for this conversation, or return its live one."""
    if not available():
        raise RuntimeError("The terminal isn't available on Windows yet.")
    cleanup_idle()
    with _registry_lock:
        for s in _sessions.values():
            if s.conversation_id == conversation_id and s.alive and s.cwd == cwd:
                s.last_seen = time.time()
                return s
        if sum(1 for s in _sessions.values() if s.alive) >= MAX_SESSIONS:
            raise RuntimeError(f"Too many open terminals (limit {MAX_SESSIONS}). Close one first.")

    import pty

    env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor", "ZENITH_TERMINAL": "1"}
    pid, fd = pty.fork()
    if pid == 0:  # child
        try:
            os.chdir(cwd)
            argv = _shell()
            os.execvpe(argv[0], argv, env)
        finally:
            os._exit(127)
    s = Session(id=secrets.token_urlsafe(12), conversation_id=conversation_id, pid=pid, fd=fd, cwd=cwd)
    s.changed = threading.Condition()
    _resize_fd(fd, cols, rows)
    with _registry_lock:
        _sessions[s.id] = s
    threading.Thread(target=_reader, args=(s,), daemon=True, name=f"terminal-{s.id}").start()
    return s


def get(session_id: str) -> Session | None:
    s = _sessions.get(session_id)
    if s is not None:
        s.last_seen = time.time()
    return s


async def read(s: Session, since: int, wait: float = 20.0) -> tuple[bytes, int, bool]:
    """Output after absolute position `since`. Waits up to `wait` seconds
    for something new (long poll). Returns (data, next_position, alive).
    If `since` is older than the kept scrollback, returns what's kept."""

    def _wait() -> None:
        assert s.changed is not None
        deadline = time.time() + wait
        with s.changed:
            while s.alive and s.end <= since and time.time() < deadline:
                s.changed.wait(timeout=max(0.0, deadline - time.time()))

    if s.end <= since and s.alive and wait > 0:
        await asyncio.to_thread(_wait)
    with s.lock:
        start_at = max(since, s.offset)
        data = bytes(s.buffer[start_at - s.offset:])
        return data, s.end, s.alive


def write(s: Session, data: str) -> None:
    if not s.alive:
        raise RuntimeError("This terminal has exited.")
    payload = data.encode()
    while payload:
        n = os.write(s.fd, payload)
        payload = payload[n:]


def _resize_fd(fd: int, cols: int, rows: int) -> None:
    import fcntl
    import termios

    cols = max(10, min(int(cols), 500))
    rows = max(2, min(int(rows), 200))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def resize(s: Session, cols: int, rows: int) -> None:
    if s.alive:
        _resize_fd(s.fd, cols, rows)


def kill(session_id: str) -> bool:
    with _registry_lock:
        s = _sessions.pop(session_id, None)
    if s is None:
        return False
    if s.alive:
        try:
            os.killpg(os.getpgid(s.pid), signal.SIGHUP)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    return True


def cleanup_idle(now: float | None = None) -> None:
    now = now or time.time()
    for sid, s in list(_sessions.items()):
        if (not s.alive and now - s.last_seen > 60) or now - s.last_seen > IDLE_TIMEOUT:
            kill(sid)


def kill_all() -> None:
    for sid in list(_sessions):
        kill(sid)
