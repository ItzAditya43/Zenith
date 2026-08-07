"""In-memory registry that decouples a chat turn's generation from the
particular HTTP connection that started it.

Without this, a dropped SSE connection (wifi blip, laptop sleep) kills the
whole turn — the async generator that's actually driving the Ollama stream
lives inside the request handler, so when Starlette closes it on
disconnect, generation stops mid-sentence and nothing gets persisted (see
the old "don't persist a half-empty response on disconnect" comment this
replaces). Instead, generation now runs as an independent background task
that outlives any single subscriber; the original request and any later
`/resume` reconnect are just subscribers reading the same buffered frame
list, replayed from the start on attach.

Scoped to the plain `/api/chat` path only (not agent/council/research) —
those have their own multi-step or fan-out loops; this covers the
everyday case first.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.core.logging import get_logger

log = get_logger(__name__)

# A run is kept around for a while after finishing so a reconnect that
# happens moments after completion can still fetch the tail instead of
# hitting a cold 404 — but not forever, or this leaks memory across a
# long-running process.
_RUN_TTL_SECONDS = 300


@dataclass
class Run:
    buffer: list[str] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    done: bool = False
    finished_at: float | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def start(self, key: str) -> Run:
        run = Run()
        self._runs[key] = run
        return run

    async def publish(self, key: str, frame: str) -> None:
        run = self._runs.get(key)
        if not run:
            return
        async with run.lock:
            run.buffer.append(frame)
            for q in run.subscribers:
                q.put_nowait(frame)

    async def finish(self, key: str) -> None:
        run = self._runs.get(key)
        if not run:
            return
        async with run.lock:
            run.done = True
            run.finished_at = time.monotonic()
            for q in run.subscribers:
                q.put_nowait(None)  # sentinel

    async def subscribe(self, key: str) -> asyncio.Queue | None:
        """Returns a queue pre-loaded with everything buffered so far, or
        None if there's no such run (nothing to resume — either it never
        existed or it's aged out)."""
        run = self._runs.get(key)
        if not run:
            return None
        if run.done and run.finished_at and time.monotonic() - run.finished_at > _RUN_TTL_SECONDS:
            return None
        q: asyncio.Queue = asyncio.Queue()
        async with run.lock:
            for frame in run.buffer:
                q.put_nowait(frame)
            if run.done:
                q.put_nowait(None)
            else:
                run.subscribers.append(q)
        return q

    def cleanup_later(self, key: str, delay: float = _RUN_TTL_SECONDS) -> None:
        async def _cleanup():
            await asyncio.sleep(delay)
            self._runs.pop(key, None)

        asyncio.create_task(_cleanup())


registry = RunRegistry()
