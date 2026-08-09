"""_with_heartbeat's idle-timeout safety cutoff — a genuinely stuck
generation (model swapped out of VRAM, wedged) used to hold the
per-conversation lock forever, silently blocking every later message in
that conversation. See app/api/chat.py."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.chat import _with_heartbeat  # noqa: E402


async def _never_yields():
    # A generator that just hangs forever, like a wedged Ollama stream.
    await asyncio.sleep(999)
    yield "unreachable"


async def _yields_then_hangs():
    yield "hello "
    await asyncio.sleep(999)
    yield "unreachable"


async def _normal_stream():
    for piece in ["a", "b", "c"]:
        yield piece


@pytest.mark.asyncio
async def test_normal_stream_passes_through_unaffected():
    out = [p async for p in _with_heartbeat(_normal_stream(), interval=10, max_idle_seconds=60)]
    assert out == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_idle_timeout_fires_on_a_stuck_stream():
    with pytest.raises(TimeoutError, match="No response from the model"):
        async for _ in _with_heartbeat(_never_yields(), interval=0.05, max_idle_seconds=0.2):
            pass


@pytest.mark.asyncio
async def test_idle_clock_resets_after_a_token_arrives():
    # A token arrives before the idle cutoff, so the clock resets; the
    # subsequent hang should still trip the cutoff (not extend it), and
    # the already-received token must have been yielded first.
    received = []
    with pytest.raises(TimeoutError):
        async for piece in _with_heartbeat(_yields_then_hangs(), interval=0.05, max_idle_seconds=0.2):
            if piece is not None:
                received.append(piece)
    assert received == ["hello "]


@pytest.mark.asyncio
async def test_no_max_idle_means_no_cutoff():
    # None disables the watchdog entirely — heartbeats still fire but
    # nothing ever raises, matching the pre-existing behavior for callers
    # that don't opt in.
    async def slow_then_done():
        await asyncio.sleep(0.15)
        yield "done"

    out = [p async for p in _with_heartbeat(slow_then_done(), interval=0.05, max_idle_seconds=None)]
    assert "done" in out
    assert out.count(None) >= 1  # at least one heartbeat tick fired while waiting
