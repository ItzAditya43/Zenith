"""Running summary of the part of a long chat that no longer fits.

Only the last `max_context_messages` messages are sent to the model. Before
this, everything older was simply gone: in a long session the model forgot
decisions made at the start. Now, once messages fall out of that window, a
background step folds them into a short summary, and the summary is added
to the system context for later turns.

The summary is tied to the exact message it covers up to
(`covered_until`). If the chat is edited or a different branch is active,
so that message is no longer one of the dropped ones, the summary is
ignored and rebuilt rather than describing a conversation that no longer
exists.
"""
from __future__ import annotations

import asyncio
import time

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

BATCH = 6               # summarise once at least this many new messages have dropped out
MAX_SUMMARY_CHARS = 2400
PER_MESSAGE_CHARS = 1500

_running: set[str] = set()


def _window() -> int:
    return int(settings.get("max_context_messages", 24))


def _dropped(history: list[dict]) -> list[dict]:
    chat = [m for m in history if m.get("role") in ("user", "assistant")]
    keep = _window()
    return chat[:-keep] if len(chat) > keep else []


def _load(conversation_id: str) -> dict | None:
    from app.db.storage import _conn

    with _conn() as conn:
        row = conn.execute(
            "SELECT summary, covered_until, covered_count FROM conversation_summaries WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    return dict(row) if row else None


def _save(conversation_id: str, summary: str, covered_until: str, covered_count: int) -> None:
    from app.db.storage import _conn

    with _conn() as conn:
        conn.execute(
            """INSERT INTO conversation_summaries (conversation_id, summary, covered_until, covered_count, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(conversation_id) DO UPDATE SET
                 summary = excluded.summary, covered_until = excluded.covered_until,
                 covered_count = excluded.covered_count, updated_at = excluded.updated_at""",
            (conversation_id, summary, covered_until, covered_count, time.time()),
        )


def _valid(saved: dict | None, dropped: list[dict]) -> bool:
    if not saved or not saved.get("covered_until"):
        return False
    n = int(saved.get("covered_count") or 0)
    return 0 < n <= len(dropped) and dropped[n - 1].get("id") == saved["covered_until"]


def summary_block(conversation_id: str, history: list[dict]) -> str:
    """System-context section for this turn, or "" when there's no valid
    summary or nothing has dropped out of the window yet."""
    if not settings.get("summarize_long_chats", True):
        return ""
    dropped = _dropped(history)
    if not dropped:
        return ""
    saved = _load(conversation_id)
    if not _valid(saved, dropped):
        return ""
    assert saved is not None
    gap = len(dropped) - int(saved["covered_count"])
    note = f" ({gap} more recent older messages aren't summarised yet)" if gap else ""
    return (
        "Summary of the earlier part of this conversation. Those messages are no longer shown "
        f"in full{note}; rely on this for what was decided or established:\n" + saved["summary"]
    )


def _render(messages: list[dict]) -> str:
    out = []
    for m in messages:
        text = (m.get("content") or "").strip()
        if len(text) > PER_MESSAGE_CHARS:
            text = text[:PER_MESSAGE_CHARS] + " …"
        out.append(f"{m['role'].upper()}: {text}")
    return "\n\n".join(out)


async def _pick_model() -> str | None:
    from app.services import model_health
    from app.services.router import ModelRegistry, ModelRouter, is_cloud_model

    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    for role in ("general", "small_fast"):
        m = router._match_capability(role, installed)  # noqa: SLF001
        if m and not model_health.is_unavailable(m) and (not is_cloud_model(m) or settings.get("route_to_cloud_models", False)):
            return m
    return None


async def update(conversation_id: str) -> bool:
    """Fold newly dropped messages into the summary. Returns True if it
    wrote a new one. Safe to call after every turn: it does nothing until
    BATCH messages have dropped out since the last summary."""
    if not settings.get("summarize_long_chats", True) or conversation_id in _running:
        return False
    from app.db import storage

    history = await asyncio.to_thread(storage.get_messages, conversation_id)
    dropped = _dropped(history)
    if not dropped:
        return False
    saved = await asyncio.to_thread(_load, conversation_id)
    if _valid(saved, dropped):
        assert saved is not None
        start, previous = int(saved["covered_count"]), saved["summary"]
    else:
        start, previous = 0, ""
    new = dropped[start:]
    if len(new) < BATCH and start > 0:
        return False
    if not new:
        return False

    _running.add(conversation_id)
    try:
        model = await _pick_model()
        if not model:
            return False
        from app.services.ollama_client import OllamaClient

        prompt = (
            "You maintain a running summary of a long conversation between a user and an AI "
            "assistant, so the assistant can keep track after older messages are dropped.\n\n"
            + (f"Summary so far:\n{previous}\n\n" if previous else "")
            + f"Older messages to fold in:\n{_render(new)}\n\n"
            "Write the updated summary as short bullet points: the user's goals, decisions made, "
            "facts and constraints they gave, names of files, functions and things being worked "
            "on, and anything still open. Keep it under 250 words. Don't add commentary. "
            "Reply with only the bullet points."
        )
        text = (await OllamaClient().chat(model, [{"role": "user", "content": prompt}])).strip()
        if not text:
            return False
        await asyncio.to_thread(_save, conversation_id, text[:MAX_SUMMARY_CHARS], dropped[-1]["id"], len(dropped))
        log.info("summary.updated", conversation_id=conversation_id, covered=len(dropped), model=model)
        return True
    except Exception as exc:
        log.debug("summary.update_failed", error=str(exc))
        return False
    finally:
        _running.discard(conversation_id)
