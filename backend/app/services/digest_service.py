"""Ambient daily digest — an opt-in, unprompted "what changed" summary
generated on an interval (see main.py's background task), built from
precise deltas already tracked elsewhere in the app (the folder watcher's
per-file mtime index, memory extraction timestamps), not fuzzy recall.

Off by default (`digest_enabled`). When on, `maybe_run_digest()` is
polled by a background task the same way the folder scanner and schedule
runner are; it only actually generates when enough time has passed since
the last one (`digest_interval_hours`).
"""
from __future__ import annotations

import time

from app.core.config import settings
from app.core.logging import get_logger
from app.db import storage
from app.services.ollama_client import OllamaClient

log = get_logger(__name__)

_DIGEST_PROMPT = """Write a short, plain-language "what's new" summary for the user based on
the concrete changes below — no more than 150 words, no headers, no bullet-point spam, just a
few sentences like a quick briefing. If there's genuinely nothing notable, say so in one
sentence rather than padding it out.

Files changed or added in watched folders:
{files}

New things learned about the user:
{memories}
"""


async def _build_and_store() -> dict | None:
    last = storage.latest_digest()
    since = last["created_at"] if last else time.time() - 24 * 3600
    files = storage.recently_indexed_files(since)
    memories = storage.recent_memories(since)

    if not files and not memories:
        log.debug("digest.nothing_new")
        return None

    files_text = "\n".join(f"- {f['path']}" for f in files[:30]) or "(none)"
    memories_text = "\n".join(f"- {m['content']}" for m in memories[:30]) or "(none)"

    try:
        from app.services.router import ModelRegistry, ModelRouter

        registry = ModelRegistry()
        installed = await registry.models()
        r = ModelRouter(registry=registry)
        model = None
        for role in ("general", "small_fast"):
            model = r._match_capability(role, installed)  # noqa: SLF001
            if model:
                break
        if not model and installed:
            model = installed[0]
        if not model:
            return None

        text = await OllamaClient().chat(
            model,
            [{"role": "user", "content": _DIGEST_PROMPT.format(files=files_text, memories=memories_text)}],
        )
    except Exception as exc:
        log.warning("digest.generate_failed", error=str(exc))
        return None

    return storage.create_digest(text.strip(), len(files), len(memories))


async def run_now() -> dict | None:
    """Explicit, on-demand generation — used by the manual 'Generate now'
    action and by the background poller once it decides enough time has
    passed."""
    return await _build_and_store()


async def maybe_run_digest() -> None:
    if not bool(settings.get("digest_enabled", False)):
        return
    interval_seconds = float(settings.get("digest_interval_hours", 24)) * 3600
    last = storage.latest_digest()
    if last and (time.time() - last["created_at"]) < interval_seconds:
        return
    await run_now()
