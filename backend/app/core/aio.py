"""Run a coroutine to completion from synchronous code, whatever the context.

Several services (RAG, memory) are synchronous but need one async Ollama
call. `asyncio.run()` works from a worker thread but *raises* when called
from inside the running event loop — and those call sites caught the
exception, so embeddings were silently skipped whenever a sync helper was
reached from an async route (e.g. memory_service.add_memory). This helper
runs the coroutine on a short-lived private thread in that case instead.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def _target() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # re-raised in the caller's thread
            result["error"] = exc

    t = threading.Thread(target=_target, name="zenith-run-sync", daemon=True)
    t.start()
    t.join()
    if "error" in result:
        raise result["error"]
    return result["value"]
