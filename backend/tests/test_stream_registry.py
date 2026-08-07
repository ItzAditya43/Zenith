"""stream_registry.py — the in-memory run buffer/replay mechanism that
lets a dropped SSE connection reconnect and pick up a chat reply where it
left off instead of losing it (see app/api/chat.py's /chat/resume)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.stream_registry import RunRegistry  # noqa: E402


@pytest.mark.asyncio
async def test_subscribe_before_run_started_returns_none():
    reg = RunRegistry()
    assert await reg.subscribe("missing") is None


@pytest.mark.asyncio
async def test_publish_then_subscribe_replays_buffer():
    reg = RunRegistry()
    reg.start("c1")
    await reg.publish("c1", "frame-1")
    await reg.publish("c1", "frame-2")

    q = await reg.subscribe("c1")
    assert q is not None
    assert await q.get() == "frame-1"
    assert await q.get() == "frame-2"


@pytest.mark.asyncio
async def test_late_subscriber_gets_live_frames_after_replay():
    reg = RunRegistry()
    reg.start("c1")
    await reg.publish("c1", "frame-1")

    q = await reg.subscribe("c1")
    assert await q.get() == "frame-1"

    await reg.publish("c1", "frame-2")
    assert await q.get() == "frame-2"


@pytest.mark.asyncio
async def test_finish_sends_sentinel_to_all_subscribers():
    reg = RunRegistry()
    reg.start("c1")
    q1 = await reg.subscribe("c1")
    q2 = await reg.subscribe("c1")

    await reg.finish("c1")

    assert await q1.get() is None
    assert await q2.get() is None


@pytest.mark.asyncio
async def test_subscribe_after_finish_replays_then_sentinel_immediately():
    reg = RunRegistry()
    reg.start("c1")
    await reg.publish("c1", "frame-1")
    await reg.finish("c1")

    q = await reg.subscribe("c1")
    assert await q.get() == "frame-1"
    assert await q.get() is None


@pytest.mark.asyncio
async def test_two_runs_are_independent():
    reg = RunRegistry()
    reg.start("a")
    reg.start("b")
    await reg.publish("a", "a-frame")
    await reg.publish("b", "b-frame")

    qa = await reg.subscribe("a")
    qb = await reg.subscribe("b")
    assert await qa.get() == "a-frame"
    assert await qb.get() == "b-frame"


@pytest.mark.asyncio
async def test_starting_a_new_run_replaces_the_old_one():
    reg = RunRegistry()
    reg.start("c1")
    await reg.publish("c1", "old")
    await reg.finish("c1")

    reg.start("c1")  # new turn in the same conversation
    q = await reg.subscribe("c1")
    await reg.publish("c1", "new")
    assert await q.get() == "new"
