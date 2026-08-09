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
               source_conversation_id: str | None = None,
               project_id: str | None = None) -> dict | None:
    """Insert a memory, deduped on normalized content. Returns the row,
    or None if it was a duplicate / empty. A memory saved from a
    project-scoped conversation is tagged with that project — it only
    surfaces in that project's conversations, not globally."""
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
            evicted = conn.execute(
                "SELECT id FROM memories ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            conn.execute("DELETE FROM memories WHERE id IN (SELECT id FROM memories ORDER BY created_at ASC LIMIT 1)")
            if evicted:
                try:
                    from app.services import rag_service
                    rag_service.delete_memory_chunks(evicted["id"])
                except Exception as exc:
                    log.debug("memory.evict_chunk_cleanup_failed", error=str(exc))
        conn.execute(
            """INSERT INTO memories
               (id, content, category, source_conversation_id, enabled, created_at, updated_at, project_id)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
            (mid, content, category, source_conversation_id, now, now, project_id),
        )
    # Embed for retrieval-based injection — best-effort, memory still works
    # (via the recency fallback below) if no embedding model is configured.
    try:
        from app.services import rag_service
        rag_service.index_memory(mid, content)
    except Exception as exc:
        log.debug("memory.index_failed", error=str(exc))
    log.info("memory.added", content=content[:80])
    return {"id": mid, "content": content, "category": category,
            "source_conversation_id": source_conversation_id,
            "enabled": 1, "created_at": now, "updated_at": now, "project_id": project_id}


def delete_memory(memory_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    try:
        from app.services import rag_service
        rag_service.delete_memory_chunks(memory_id)
    except Exception as exc:
        log.debug("memory.delete_chunk_cleanup_failed", error=str(exc))
    try:
        from app.db.storage import clear_memory_conflicts_for
        clear_memory_conflicts_for(memory_id)
    except Exception as exc:
        log.debug("memory.conflict_cleanup_failed", error=str(exc))


def set_enabled(memory_id: str, enabled: bool) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE memories SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, time.time(), memory_id),
        )


def clear_memories() -> int:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM memories")
    try:
        from app.services import rag_service
        rag_service.clear_memory_chunks()
    except Exception as exc:
        log.debug("memory.clear_chunk_cleanup_failed", error=str(exc))
    return cur.rowcount


def memory_block(project_id: str | None = None, query: str | None = None) -> str:
    """Render memories relevant to `query` as a system-prompt section,
    instead of dumping every stored memory into every turn. At small
    counts (<= top_k) everything just gets included — retrieval overhead
    isn't worth it until there's actually something to filter. Falls back
    to most-recent-first if no query is given or no embedding model is
    configured (same degrade-gracefully pattern as document RAG).
    Project-scoped memories only surface for conversations in that same
    project; global (unscoped) memories always surface."""
    if not bool(settings.get("memory_enabled", True)):
        return ""
    visible = [
        m for m in list_memories()
        if m["enabled"] and (not m.get("project_id") or m.get("project_id") == project_id)
    ]
    if not visible:
        return ""

    top_k = int(settings.get("memory_recall_top_k", 12))
    if len(visible) <= top_k:
        mems = visible
    else:
        mems = None
        if query and query.strip():
            try:
                from app.services import rag_service
                visible_ids = {m["id"] for m in visible}
                by_id = {m["id"]: m for m in visible}
                hits = rag_service.retrieve(query, source_kind="memory", top_k=top_k)
                picked = [by_id[h["source_id"]] for h in hits if h["source_id"] in visible_ids]
                if picked:
                    mems = picked
            except Exception as exc:
                log.debug("memory.retrieval_failed", error=str(exc))
        if mems is None:
            # No query, no embedding model, or retrieval came back empty —
            # most-recent-first is a reasonable, cheap default.
            mems = sorted(visible, key=lambda m: m["created_at"], reverse=True)[:top_k]

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
        project_id = None
        if conversation_id:
            from app.db.storage import get_conversation
            conv = get_conversation(conversation_id)
            project_id = conv.get("project_id") if conv else None
        added = []
        for fact in facts[:5]:
            row = add_memory(fact, source_conversation_id=conversation_id, project_id=project_id)
            if row:
                added.append(row)
        return added
    except Exception as exc:
        log.debug("memory.extract_failed", error=str(exc))
        return []


_CONFLICT_REVIEW_PROMPT = """Below is a numbered list of facts a personal AI assistant remembers
about its user. Some may contradict each other because the user's situation changed and the
old fact was never removed (e.g. "uses fish shell" vs "uses zsh", "lives in Berlin" vs "lives
in Lisbon"). Find pairs that genuinely contradict — not just related or similar facts, only
ones that can't both be true at once.

Respond with ONLY a JSON array of objects: [{"a": <index>, "b": <index>, "reason": "<short reason>"}].
Return [] if you find no contradictions. No prose, no markdown fence.

Facts:
"""


async def review_conflicts() -> list[dict]:
    """Scans enabled memories for pairwise contradictions with a small
    model and persists any found as unresolved `memory_conflicts` rows —
    an explicit, on-demand action (Settings -> Memory -> "Review for
    conflicts"), not automatic on every save, since an LLM scan over
    every memory isn't cheap enough to run silently and constantly.
    Returns the newly created conflict rows."""
    mems = [m for m in list_memories(include_disabled=False)]
    if len(mems) < 2:
        return []
    try:
        from app.db.storage import create_memory_conflict
        from app.services.router import ModelRegistry, ModelRouter

        registry = ModelRegistry()
        installed = await registry.models()
        r = ModelRouter(registry=registry)
        model = None
        # Unlike per-message fact extraction, this compares every pair of
        # memories for a genuine contradiction — small_fast models (tuned
        # for one-line "did they say anything worth remembering" calls)
        # tend to produce malformed JSON on this multi-item comparison
        # task, so prefer the general-purpose model first.
        for role in ("general", "small_fast"):
            model = r._match_capability(role, installed)  # noqa: SLF001
            if model:
                break
        if not model and installed:
            model = installed[0]
        if not model:
            return []

        numbered = "\n".join(f"{i}. {m['content']}" for i, m in enumerate(mems))
        out = await OllamaClient().chat(
            model, [{"role": "user", "content": _CONFLICT_REVIEW_PROMPT + numbered}]
        )
        # Non-greedy: a small model's reply sometimes has trailing prose
        # with its own brackets after the JSON array, which a greedy
        # match would swallow and then fail to parse as one JSON value.
        m_json = re.search(r"\[.*?\]", out, re.DOTALL)
        if not m_json:
            return []
        pairs = json.loads(m_json.group(0))

        created = []
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            a, b, reason = pair.get("a"), pair.get("b"), pair.get("reason", "")
            if not isinstance(a, int) or not isinstance(b, int) or a == b:
                continue
            if not (0 <= a < len(mems)) or not (0 <= b < len(mems)):
                continue
            row = create_memory_conflict(mems[a]["id"], mems[b]["id"], str(reason)[:300])
            created.append(row)
        log.info("memory.conflict_review", scanned=len(mems), found=len(created))
        return created
    except Exception as exc:
        log.warning("memory.conflict_review_failed", error=str(exc))
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
