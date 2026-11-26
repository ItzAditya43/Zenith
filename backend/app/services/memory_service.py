"""Long-term user memory (personal-use feature).

Two halves:

1. **Extraction** — after each turn, a small/fast model reads the user's
   message and pulls out durable personal facts ("uses Arch Linux",
   "allergic to peanuts", "building an app called atlas"). Stored in the
   `memories` table, deduped by normalized content. Fire-and-forget: never
   blocks or breaks a chat turn.

2. **Injection** — `memory_block()` renders the enabled memories as a
   system-prompt section the orchestrator prepends to every turn, so any
   model the router picks knows who it's talking to.

Each memory has a scope (global, one project, or one conversation), a
link to the message it came from, the extractor's confidence, and a use
count. Uncertain or sensitive facts are saved as *pending* and never used
until the user approves them; topics on the exclusion list are never saved.
The memory browser (/api/memories) can search, edit, merge, disable,
forget and export them, and each reply lists the memories it was given.
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

Respond with ONLY a JSON array of objects:
[{"fact": "<standalone fact, max 15 words>", "confidence": <0..1 how sure this is durable and true>,
  "sensitive": <true if health, finances, relationships, identity documents, location or other private details>}]
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


def get_memory(memory_id: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return dict(r) if r else None


def search_memories(q: str = "", scope: str | None = None, status: str | None = None,
                    project_id: str | None = None, conversation_id: str | None = None) -> list[dict]:
    """The memory browser's list: text search plus scope/status filters,
    with the source conversation's title for provenance."""
    sql = ("SELECT m.*, c.title AS source_title FROM memories m "
           "LEFT JOIN conversations c ON c.id = m.source_conversation_id WHERE 1=1")
    args: list = []
    if q.strip():
        sql += " AND lower(m.content) LIKE ?"
        args.append(f"%{q.strip().lower()}%")
    if scope:
        sql += " AND m.scope = ?"
        args.append(scope)
    if status:
        sql += " AND m.status = ?"
        args.append(status)
    if project_id:
        sql += " AND m.project_id = ?"
        args.append(project_id)
    if conversation_id:
        sql += " AND (m.scope_conversation_id = ? OR m.source_conversation_id = ?)"
        args += [conversation_id, conversation_id]
    sql += " ORDER BY (m.status = 'pending') DESC, m.updated_at DESC"
    with _conn() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _exclusions() -> list[str]:
    raw = settings.get("memory_exclusions") or []
    if isinstance(raw, str):
        raw = [x for x in re.split(r"[,\n]", raw)]
    return [x.strip().lower() for x in raw if str(x).strip()]


def is_excluded(content: str) -> bool:
    low = content.lower()
    return any(term in low for term in _exclusions())


def _reindex(memory_id: str, content: str) -> None:
    try:
        from app.services import rag_service
        rag_service.delete_memory_chunks(memory_id)
        rag_service.index_memory(memory_id, content)
    except Exception as exc:
        log.debug("memory.reindex_failed", error=str(exc))


def update_memory(memory_id: str, *, content: str | None = None, enabled: bool | None = None,
                  scope: str | None = None, conversation_id: str | None = None,
                  project_id: str | None = None, status: str | None = None) -> dict | None:
    """Edit any field the browser exposes. Returns the updated row, or None
    if it doesn't exist. Raises ValueError for a duplicate/invalid edit."""
    row = get_memory(memory_id)
    if not row:
        return None
    sets, args = [], []
    if content is not None:
        content = " ".join(content.split()).strip().rstrip(".")
        if not content or len(content) > 300:
            raise ValueError("A memory must be 1–300 characters.")
        with _conn() as conn:
            dup = conn.execute("SELECT id FROM memories WHERE lower(content) = lower(?) AND id != ?",
                               (content, memory_id)).fetchone()
        if dup:
            raise ValueError("Another memory already says that.")
        sets.append("content = ?")
        args.append(content)
    if enabled is not None:
        sets.append("enabled = ?")
        args.append(1 if enabled else 0)
    if status is not None:
        if status not in ("active", "pending"):
            raise ValueError("Unknown status.")
        sets.append("status = ?")
        args.append(status)
    if scope is not None:
        if scope not in ("global", "project", "conversation"):
            raise ValueError("Unknown scope.")
        pid = project_id if scope == "project" else None
        cid = conversation_id if scope == "conversation" else None
        if scope == "project" and not (pid or row.get("project_id")):
            raise ValueError("Pick a project for a project memory.")
        if scope == "conversation" and not (cid or row.get("scope_conversation_id") or row.get("source_conversation_id")):
            raise ValueError("Pick a conversation for a conversation memory.")
        sets += ["scope = ?", "project_id = ?", "scope_conversation_id = ?"]
        args += [scope, pid or (row.get("project_id") if scope == "project" else None),
                 cid or ((row.get("scope_conversation_id") or row.get("source_conversation_id")) if scope == "conversation" else None)]
    if not sets:
        return row
    sets.append("updated_at = ?")
    args.append(time.time())
    with _conn() as conn:
        conn.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", (*args, memory_id))
    if content is not None:
        _reindex(memory_id, content)
    return get_memory(memory_id)


def merge_memories(ids: list[str], content: str) -> dict:
    """Replace several memories with one. The new memory keeps the earliest
    source, the widest scope among them, and their combined use count."""
    rows = [r for r in (get_memory(i) for i in ids) if r]
    if len(rows) < 2:
        raise ValueError("Pick at least two memories to merge.")
    content = " ".join(content.split()).strip().rstrip(".")
    if not content or len(content) > 300:
        raise ValueError("A memory must be 1–300 characters.")
    order = {"global": 0, "project": 1, "conversation": 2}
    widest = min(rows, key=lambda r: order.get(r.get("scope") or "global", 0))
    earliest = min(rows, key=lambda r: r["created_at"])
    for r in rows:
        delete_memory(r["id"])
    new = add_memory(content, category=earliest.get("category") or "fact",
                     source_conversation_id=earliest.get("source_conversation_id"),
                     project_id=widest.get("project_id"), scope=widest.get("scope") or "global",
                     scope_conversation_id=widest.get("scope_conversation_id"),
                     source_message_id=earliest.get("source_message_id"), confidence=1.0, force=True)
    if new is None:
        raise ValueError("That memory already exists.")
    with _conn() as conn:
        conn.execute("UPDATE memories SET use_count = ?, created_at = ? WHERE id = ?",
                     (sum(int(r.get("use_count") or 0) for r in rows), earliest["created_at"], new["id"]))
    return get_memory(new["id"]) or new


def export_memories() -> list[dict]:
    keep = ("id", "content", "category", "scope", "project_id", "scope_conversation_id",
            "source_conversation_id", "source_message_id", "confidence", "status", "enabled",
            "use_count", "last_used_at", "created_at", "updated_at")
    return [{k: m.get(k) for k in keep} for m in list_memories()]


def mark_used(ids: list[str]) -> None:
    if not ids:
        return
    now = time.time()
    with _conn() as conn:
        conn.executemany("UPDATE memories SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                         [(now, i) for i in ids])


def add_memory(content: str, category: str = "fact",
               source_conversation_id: str | None = None,
               project_id: str | None = None, *, scope: str | None = None,
               scope_conversation_id: str | None = None,
               source_message_id: str | None = None,
               confidence: float | None = None, status: str = "active",
               force: bool = False) -> dict | None:
    """Insert a memory, deduped on normalized content. Returns the row,
    or None if it was a duplicate / empty. A memory saved from a
    project-scoped conversation is tagged with that project — it only
    surfaces in that project's conversations, not globally."""
    content = " ".join(content.split()).strip().rstrip(".")
    if not content or len(content) > 300:
        return None
    if not force and is_excluded(content):
        log.info("memory.excluded")
        return None
    if scope is None:
        scope = "project" if project_id else "global"
    now = time.time()
    mid = str(uuid.uuid4())
    evicted_id: str | None = None
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
            evicted_id = evicted["id"] if evicted else None
        conn.execute(
            """INSERT INTO memories
               (id, content, category, source_conversation_id, enabled, created_at, updated_at, project_id,
                scope, scope_conversation_id, source_message_id, confidence, status)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mid, content, category, source_conversation_id, now, now, project_id,
             scope, scope_conversation_id, source_message_id, confidence, status),
        )
    # Chunk cleanup only after the transaction above has committed: RAG uses
    # its own connection, and doing this inside it deadlocked on the write
    # lock for the full busy_timeout, then left the evicted memory retrievable.
    if evicted_id:
        try:
            from app.services import rag_service
            rag_service.delete_memory_chunks(evicted_id)
        except Exception as exc:
            log.warning("memory.evict_chunk_cleanup_failed", error=str(exc))
    # Embed for retrieval-based injection — best-effort, memory still works
    # (via the recency fallback below) if no embedding model is configured.
    try:
        from app.services import rag_service
        rag_service.index_memory(mid, content)
    except Exception as exc:
        log.debug("memory.index_failed", error=str(exc))
    log.info("memory.added", content=content[:80])
    return get_memory(mid) or {"id": mid, "content": content, "category": category,
                                "source_conversation_id": source_conversation_id, "enabled": 1,
                                "created_at": now, "updated_at": now, "project_id": project_id,
                                "scope": scope, "status": status}


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


def memory_block(project_id: str | None = None, query: str | None = None,
                 conversation_id: str | None = None) -> str:
    return memory_context(project_id, query, conversation_id)[0]


def _visible(m: dict, project_id: str | None, conversation_id: str | None) -> bool:
    if not m["enabled"] or (m.get("status") or "active") != "active":
        return False
    scope = m.get("scope") or ("project" if m.get("project_id") else "global")
    if scope == "project":
        return bool(project_id) and m.get("project_id") == project_id
    if scope == "conversation":
        return bool(conversation_id) and (m.get("scope_conversation_id") or m.get("source_conversation_id")) == conversation_id
    return True


def memory_context(project_id: str | None = None, query: str | None = None,
                   conversation_id: str | None = None) -> tuple[str, list[dict]]:
    """Render memories relevant to `query` as a system-prompt section,
    instead of dumping every stored memory into every turn. At small
    counts (<= top_k) everything just gets included — retrieval overhead
    isn't worth it until there's actually something to filter. Falls back
    to most-recent-first if no query is given or no embedding model is
    configured (same degrade-gracefully pattern as document RAG).
    Project-scoped memories only surface for conversations in that same
    project; global (unscoped) memories always surface."""
    if not bool(settings.get("memory_enabled", True)):
        return "", []
    visible = [m for m in list_memories() if _visible(m, project_id, conversation_id)]
    if not visible:
        return "", []

    top_k = int(settings.get("memory_recall_top_k", 12))
    mems: list[dict] | None
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

    mems = mems or []
    lines = "\n".join(f"- {m['content']}" for m in mems)
    try:
        mark_used([m["id"] for m in mems])
    except Exception as exc:
        log.debug("memory.mark_used_failed", error=str(exc))
    return (
        "Things you remember about the user from previous conversations "
        "(use them naturally when relevant, don't recite them):\n" + lines
    ), mems


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
        facts = _parse_scored_facts(out)
        project_id = None
        source_message_id = None
        if conversation_id:
            from app.db.storage import get_conversation, get_messages
            conv = get_conversation(conversation_id)
            project_id = conv.get("project_id") if conv else None
            try:
                for m in reversed(get_messages(conversation_id)):
                    if m.get("role") == "user" and (m.get("content") or "").strip() == user_text.strip():
                        source_message_id = m.get("id")
                        break
            except Exception as exc:
                log.debug("memory.source_lookup_failed", error=str(exc))
        threshold = float(settings.get("memory_approval_threshold", 0.6))
        always_ask = bool(settings.get("memory_require_approval", False))
        added = []
        for fact, confidence, sensitive in facts[:5]:
            pending = always_ask or sensitive or confidence < threshold
            row = add_memory(fact, source_conversation_id=conversation_id, project_id=project_id,
                             source_message_id=source_message_id, confidence=confidence,
                             status="pending" if pending else "active")
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
        pairs = _first_json_array(out)
        if pairs is None:
            return []

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
        if created:
            try:
                from app.services import events
                await events.emit("memory_conflict_found", {"count": len(created)})
            except Exception as exc:
                log.debug("memory.event_emit_failed", error=str(exc))
        return created
    except Exception as exc:
        log.warning("memory.conflict_review_failed", error=str(exc))
        return []


def _first_json_array(raw: str) -> list | None:
    """The first complete JSON array in a model reply, tolerating fences
    and prose on either side. A regex can't do this: greedy `\\[.*\\]`
    swallows brackets in trailing prose, non-greedy stops at a `]` inside
    a string ("uses [zsh]")."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\[", raw or ""):
        try:
            value, _ = decoder.raw_decode(raw, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            return value
    return None


def _parse_scored_facts(raw: str) -> list[tuple[str, float, bool]]:
    """[(fact, confidence, sensitive)] from the extractor's reply. Accepts
    the scored object format and the older plain list of strings (treated
    as confident and not sensitive)."""
    arr = _first_json_array(raw)
    out: list[tuple[str, float, bool]] = []
    if arr is None:
        return [(f, 1.0, False) for f in _parse_facts(raw)]
    for item in arr:
        if isinstance(item, str) and item.strip():
            out.append((item.strip(), 1.0, False))
        elif isinstance(item, dict):
            fact = str(item.get("fact") or item.get("text") or "").strip()
            if not fact:
                continue
            try:
                conf = max(0.0, min(1.0, float(item.get("confidence", 1.0))))
            except (TypeError, ValueError):
                conf = 1.0
            out.append((fact, conf, bool(item.get("sensitive"))))
    return out


def _parse_facts(raw: str) -> list[str]:
    """Parse the model's reply into a list of fact strings. Tolerates
    markdown fences and stray prose around the JSON array."""
    arr = _first_json_array(raw)
    if not arr:
        return []
    return [f.strip() for f in arr if isinstance(f, str) and f.strip()]
