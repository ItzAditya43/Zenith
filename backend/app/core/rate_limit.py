"""Per-conversation async request queue (Tier 7 #2).

Prevents a client from piling up concurrent /api/chat requests for the same
conversation, which would fan out to N simultaneous Ollama streams and OOM the
host. Each conversation gets a single-slot lock; callers `async with
conversation_lock(cid):` and only one turn runs at a time. Different
conversations run in parallel (that's fine — they're independent).
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


@asynccontextmanager
async def conversation_lock(conversation_id: str, timeout: float | None = None):
    """Serialize turns per conversation. Raises TimeoutError if a queued
    request waits longer than `timeout` seconds (default: 60)."""
    async with _locks_guard:
        lock = _locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            _locks[conversation_id] = lock

    t0 = time.time()
    if timeout is None:
        timeout = float(settings.get("chat_queue_timeout_seconds", 60))
    try:
        await asyncio.wait_for(lock.acquire(), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("ratelimit.queue_timeout", conversation_id=conversation_id)
        raise TimeoutError(
            "Too many in-flight requests for this conversation; try again shortly."
        )
    try:
        yield
    finally:
        lock.release()
        # Drop the lock object if no one is waiting, to avoid unbounded growth.
        if not lock.locked():
            async with _locks_guard:
                if conversation_id in _locks and not _locks[conversation_id].locked():
                    _locks.pop(conversation_id, None)