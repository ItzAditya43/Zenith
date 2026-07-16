"""Generate a short (≤5 words) conversation title from the first
assistant response. Runs in a background task so the SSE close isn't
blocked. Best-effort: silently no-ops on any failure."""
from __future__ import annotations

import asyncio
import re

from app.core.config import settings
from app.core.logging import get_logger
from app.db import storage
from app.services.ollama_client import OllamaClient, OllamaError

log = get_logger(__name__)


async def generate_title(seed_text: str) -> str | None:
    """Ask a small model for a ≤5-word title based on `seed_text`.
    Returns None on any failure (no models, Ollama down, junk output)."""
    try:
        client = OllamaClient()
        # Use the smallest "fast" model if available, else the general
        # one. The actual pick is best-effort.
        from app.services.router import ModelRegistry
        registry = ModelRegistry()
        try:
            installed = await registry.models()
        except Exception:
            installed = []
        model = None
        from app.services.router import ModelRouter
        r = ModelRouter(registry=registry)
        for role in ("small_fast", "general"):
            model = r._match_capability(role, installed)  # noqa: SLF001
            if model:
                break
        if not model and installed:
            model = installed[0]
        if not model:
            return None
        prompt = (
            "Generate a short conversation title (max 5 words, no quotes, no trailing punctuation) "
            "that captures the topic of the following text. Reply with ONLY the title:\n\n"
            + seed_text[:500]
        )
        out = await client.chat(model, [{"role": "user", "content": prompt}])
        title = (out or "").strip().splitlines()[0].strip().strip("\"'`")
        title = re.sub(r"[^A-Za-z0-9 _-]", "", title).strip()
        words = title.split()
        if len(words) > 5:
            title = " ".join(words[:5])
        if 1 <= len(title) <= 60:
            return title
        return None
    except (OllamaError, Exception) as exc:
        log.debug("title.generate_failed", error=str(exc))
        return None


async def _do_generate(conversation_id: str, first_reply: str) -> None:
    title = await generate_title(first_reply)
    if title:
        storage.rename_conversation(conversation_id, title)


def maybe_generate_title(conversation_id: str, first_reply: str) -> None:
    """Fire-and-forget. Spawns a background asyncio task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_do_generate(conversation_id, first_reply))
        else:
            asyncio.run(_do_generate(conversation_id, first_reply))
    except Exception as exc:
        log.debug("title.spawn_failed", error=str(exc))