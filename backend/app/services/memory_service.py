"""Long-term user memory (personal-use feature).

Two halves:

1. **Extraction** — after each turn, a small/fast model reads the user's
   message and pulls out durable personal facts ("uses Arch Linux",
   "allergic to peanuts", "building an app called cortex"). Stored in the
   `memories` table, deduped by normalized content. Fire-and-forget: never
   blocks or breaks a chat turn.

2. **Injection** — `memory_block()` renders the enabled memories as a
   system-prompt section the orchestrator prepends to every turn, so any
   model the router picks knows who it's talking to.

The user can view/delete/disable memories via /api/memories (Settings UI).
"""
from __future__ import annotations

import json
import re
import time
import uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.db.storage import _conn
from app.services.ollama_client import OllamaClient

log = get_logger(__name__)

_EXTRACT_PROMPT = """You extract long-term memory for a personal AI assistant.
From the user message below, list durable facts worth remembering across
conversations: stable preferences, personal details, ongoing projects, likes/dislikes,
tools they use. IGNORE one-off requests, questions, pleasantries, and anything transient.

Respond with ONLY a JSON array of short strings (each a standalone fact, max 15 words).
Return [] if there is nothing worth remembering. No prose, no markdown fence.

User message:
"""


def list_memories(include_disabled: bool = True) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM memories ORDER BY created_at DESC"
            if include_disabled
            else "SELECT * FROM memories WHERE enabled = 1 ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def add_memory(content: str, category: str = "fact",
               source_conversation_id: str | None = None) -> dict | None:
    """Insert a memory, deduped on normalized content. Returns the row,
    or None if it was a duplicate / empty."""
    content = " ".join(content.split()).strip().rstrip(".")
    if not content or len(content) > 300:
        return None
    now = time.time()
    mid = str(uuid.uuid4())
    with _conn() as conn:
        # Case-insensitive dedupe against existing rows.
        dup = conn.execute(
            "SELECT id FROM memories WHERE lower(content) = lower(?)", (content,)
        ).fetchone()
        if dup:
            return None
        cap = int(settings.get("memory_max_items", 200))
        count = conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
        if count >= cap:
            # Evict the oldest so memory stays bounded.
            conn.execute(
                "DELETE FROM memories WHERE id IN ("
                "SELECT id FROM memories ORDER BY created_at ASC LIMIT 1)"
            )
        conn.execute(
            """INSERT INTO memories
               (id, content, category, source_conversation_id, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (mid, content, category, source_conversation_id, now, now),
        )
    log.info("memory.added", content=content[:80])
    return {"id": mid, "content": content, "category": category,
            "source_conversation_id": source_conversation_id,
            "enabled": 1, "created_at": now, "updated_at": now}


def delete_memory(memory_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))


def set_enabled(memory_id: str, enabled: bool) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE memories SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, time.time(), memory_id),
        )


def clear_memories() -> int:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM memories")
        return cur.rowcount


def memory_block() -> str:
    """Render enabled memories as a system-prompt section. Empty string
    when memory is off or there's nothing stored."""
    if not bool(settings.get("memory_enabled", True)):
        return ""
    mems = [m for m in list_memories() if m["enabled"]]
    if not mems:
        return ""
    lines = "\n".join(f"- {m['content']}" for m in mems)
    return (
        "Things you remember about the user from previous conversations "
        "(use them naturally when relevant, don't recite them):\n" + lines
    )


async def extract_from_text(user_text: str,
                            conversation_id: str | None = None) -> list[dict]:
    """Ask a small model for durable facts in `user_text` and store them.
    Best-effort: returns the list of newly added memories ([] on any
    failure). Skips trivially short messages."""
    if not bool(settings.get("memory_enabled", True)):
        return []
    if not user_text or len(user_text.strip()) < 15:
        return []
    try:
        from app.services.router import ModelRegistry, ModelRouter

        registry = ModelRegistry()
        installed = await registry.models()
        r = ModelRouter(registry=registry)
        model = None
        for role in ("small_fast", "general"):
            model = r._match_capability(role, installed)  # noqa: SLF001
            if model:
                break
        if not model and installed:
            model = installed[0]
        if not model:
            return []
        out = await OllamaClient().chat(
            model, [{"role": "user", "content": _EXTRACT_PROMPT + user_text[:2000]}]
        )
        facts = _parse_facts(out)
        added = []
        for fact in facts[:5]:
            row = add_memory(fact, source_conversation_id=conversation_id)
            if row:
                added.append(row)
        return added
    except Exception as exc:
        log.debug("memory.extract_failed", error=str(exc))
        return []


def _parse_facts(raw: str) -> list[str]:
    """Parse the model's reply into a list of fact strings. Tolerates
    markdown fences and stray prose around the JSON array."""
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [f.strip() for f in arr if isinstance(f, str) and f.strip()]
