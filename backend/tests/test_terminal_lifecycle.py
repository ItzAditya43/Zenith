"""Interrupt stops the foreground command; kill escalates; sessions are listed."""
from __future__ import annotations

import time

import pytest

from app.services import terminal_service as ts

pytestmark = pytest.mark.skipif(not ts.available(), reason="no pty on this platform")


def _wait(s, needle: bytes, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        with s.lock:
            if needle in bytes(s.buffer):
                return True
        time.sleep(0.05)
    return False


def test_interrupt_list_and_kill(tmp_path):
    s = ts.start("conv", str(tmp_path))
    try:
        assert any(x["id"] == s.id for x in ts.list_sessions())
        ts.write(s, "sleep 30; echo NOT_INTERRUPTED\n")
        time.sleep(0.5)
        ts.interrupt(s)
        ts.write(s, "echo AFTER_INT\n")
        assert _wait(s, b"AFTER_INT")
        with s.lock:
            assert b"NOT_INTERRUPTED\r\n" not in bytes(s.buffer).replace(b"echo NOT_INTERRUPTED", b"")
    finally:
        assert ts.kill(s.id)
    assert all(x["id"] != s.id for x in ts.list_sessions())
