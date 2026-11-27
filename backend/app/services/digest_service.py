"""Ambient daily digest — an opt-in, unprompted "what changed" summary
generated on an interval (see main.py's background task), built from
precise deltas already tracked elsewhere in the app (the folder watcher's
per-file mtime index, memory extraction timestamps), not fuzzy recall.

Off by default (`digest_enabled`). When on, `maybe_run_digest()` is
polled by a background task the same way the folder scanner and schedule
runner are. With `digest_time` ("HH:MM", local) it runs once a day at or
after that time; otherwise every `digest_interval_hours`.

`digest_sources` picks what goes in: watched-folder files, new memories,
scheduled-run results, and to-dos completed or due soon. Every item is
stored with the digest (kind, label, link target) so the UI can show why
it appeared. Building a digest never creates memories, to-dos or any
other action — it only reads.
"""
from __future__ import annotations

import datetime as dt
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

Scheduled tasks that ran:
{schedules}

To-dos completed or due in the next day:
{todos}
"""


def _sources() -> set[str]:
    raw = settings.get("digest_sources")
    if not isinstance(raw, list):
        return {"files", "memories", "schedules", "todos"}
    return {str(x) for x in raw}


def _schedule_runs(since: float) -> list[dict]:
    from app.db.storage import _conn
    with _conn() as conn:
        rows = conn.execute(
            "SELECT r.status, r.summary, r.finished_at, s.name, s.conversation_id FROM schedule_runs r"
            " JOIN schedules s ON s.id = r.schedule_id WHERE r.finished_at >= ? ORDER BY r.finished_at DESC LIMIT 20",
            (since,)).fetchall()
    return [dict(r) for r in rows]


def _todos(since: float) -> list[dict]:
    from app.db.storage import _conn
    soon = time.time() + 86400
    with _conn() as conn:
        done = [dict(r, why="completed") for r in conn.execute(
            "SELECT id, text FROM todos WHERE done = 1 AND updated_at >= ? ORDER BY updated_at DESC LIMIT 20", (since,))]
        due = [dict(r, why="due soon") for r in conn.execute(
            "SELECT id, text FROM todos WHERE done = 0 AND due_ts IS NOT NULL AND due_ts <= ? ORDER BY due_ts LIMIT 20",
            (soon,))]
    return done + due


async def _build_and_store() -> dict | None:
    last = storage.latest_digest()
    since = last["created_at"] if last else time.time() - 24 * 3600
    src = _sources()
    files = storage.recently_indexed_files(since) if "files" in src else []
    memories = storage.recent_memories(since) if "memories" in src else []
    runs = _schedule_runs(since) if "schedules" in src else []
    todos = _todos(since) if "todos" in src else []

    if not files and not memories and not runs and not todos:
        log.debug("digest.nothing_new")
        return None

    files_text = "\n".join(f"- {f['path']}" for f in files[:30]) or "(none)"
    memories_text = "\n".join(f"- {m['content']}" for m in memories[:30]) or "(none)"
    runs_text = "\n".join(f"- {r['name']} ({r['status']}): {(r['summary'] or '')[:160]}" for r in runs) or "(none)"
    todos_text = "\n".join(f"- {t['text']} ({t['why']})" for t in todos) or "(none)"
    items = (
        [{"kind": "file", "label": f["path"], "why": "changed in a watched folder", "ref": f["path"]} for f in files[:30]]
        + [{"kind": "memory", "label": m["content"], "why": "newly remembered", "ref": m["id"]} for m in memories[:30]]
        + [{"kind": "schedule", "label": r["name"], "why": f"scheduled run — {r['status']}", "ref": r["conversation_id"]}
           for r in runs]
        + [{"kind": "todo", "label": t["text"], "why": t["why"], "ref": t["id"]} for t in todos]
    )

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
            [{"role": "user", "content": _DIGEST_PROMPT.format(files=files_text, memories=memories_text,
                                                                schedules=runs_text, todos=todos_text)}],
        )
    except Exception as exc:
        log.warning("digest.generate_failed", error=str(exc))
        return None

    digest = storage.create_digest(text.strip(), len(files), len(memories), items)
    try:
        from app.services import events
        await events.emit("digest_generated", {
            "digest_id": digest["id"], "files_changed": digest["files_changed"],
            "memories_added": digest["memories_added"],
        })
    except Exception as exc:
        log.debug("digest.event_emit_failed", error=str(exc))
    return digest


async def run_now() -> dict | None:
    """Explicit, on-demand generation — used by the manual 'Generate now'
    action and by the background poller once it decides enough time has
    passed."""
    return await _build_and_store()


async def maybe_run_digest() -> None:
    if not bool(settings.get("digest_enabled", False)):
        return
    last = storage.latest_digest()
    if not is_due(last["created_at"] if last else None, time.time()):
        return
    await run_now()


def is_due(last_ts: float | None, now: float) -> bool:
    at = str(settings.get("digest_time") or "").strip()
    if at:
        try:
            hh, mm = (int(x) for x in at.split(":"))
        except ValueError:
            at = ""
        else:
            local_now = dt.datetime.fromtimestamp(now).astimezone()
            today_at = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if local_now < today_at:
                return False
            return last_ts is None or last_ts < today_at.timestamp()
    interval_seconds = float(settings.get("digest_interval_hours", 24)) * 3600
    return last_ts is None or (now - last_ts) >= interval_seconds
