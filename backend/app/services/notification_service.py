"""Notification history and controls.

Every event that can notify (events.EVENT_TYPES) is written here, so
there's one searchable history of what happened while you were away.
Whether it also pops up on the desktop is decided here too: event types
you muted never pop up, and nothing pops up (or goes to ntfy) during quiet
hours. The history keeps everything for `notify_history_days`.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from app.core.config import settings
from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

LABELS = {
    "schedule_completed": "Scheduled task finished",
    "agent_run_finished": "Background task finished",
    "agent_run_needs_approval": "Background task needs approval",
    "digest_generated": "Daily digest ready",
    "urgent_email": "Urgent email",
    "memory_conflict_found": "Memory conflict found",
    "folder_file_added": "New file in a watched folder",
    "todo_created": "To-do added by a schedule or rule",
    "todo_completed": "To-do completed",
}


def _minutes(hhmm: str) -> int | None:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(now: datetime | None = None) -> bool:
    start = _minutes(settings.get("notify_quiet_start") or "")
    end = _minutes(settings.get("notify_quiet_end") or "")
    if start is None or end is None or start == end:
        return False
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    return start <= cur < end if start < end else (cur >= start or cur < end)


def should_pop_up(event_type: str) -> bool:
    return event_type not in (settings.get("notify_desktop_muted") or []) and not in_quiet_hours()


def _text(event_type: str, data: dict) -> tuple[str, str]:
    from app.services.notify_service import _format_message

    title, body = _format_message(event_type, data)
    return title.removeprefix("Zenith: ").capitalize(), body


DEDUPE_SECONDS = 120


def record(event_type: str, data: dict) -> dict:
    """Store one notification. The same title+body for the same event
    within DEDUPE_SECONDS is not stored again (and doesn't pop up twice)."""
    title, body = _text(event_type, data or {})
    nid = uuid.uuid4().hex[:12]
    now = time.time()
    desktop = should_pop_up(event_type)
    with _conn() as conn:
        dup = conn.execute(
            "SELECT id, title, body, desktop, created_at FROM notifications WHERE event_type = ? AND title = ? AND body = ?"
            " AND created_at >= ? ORDER BY created_at DESC LIMIT 1",
            (event_type, title, body[:1000], now - DEDUPE_SECONDS)).fetchone()
        if dup:
            return {"id": dup["id"], "event_type": event_type, "title": title, "body": body, "desktop": False,
                    "created_at": dup["created_at"], "duplicate": True}
        conn.execute(
            "INSERT INTO notifications (id, event_type, title, body, data, desktop, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nid, event_type, title, body[:1000], json.dumps(data or {}, default=str)[:4000], 1 if desktop else 0, now),
        )
        days = int(settings.get("notify_history_days", 30))
        conn.execute("DELETE FROM notifications WHERE created_at < ?", (now - days * 86400,))
    return {"id": nid, "event_type": event_type, "title": title, "body": body, "desktop": desktop, "created_at": now}


def list_notifications(q: str = "", event_type: str | None = None, since: float | None = None,
                       unread: bool = False, limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM notifications WHERE 1=1"
    args: list[object] = []
    if q.strip():
        sql += " AND (lower(title) LIKE ? OR lower(body) LIKE ?)"
        args += [f"%{q.strip().lower()}%"] * 2
    if event_type:
        sql += " AND event_type = ?"
        args.append(event_type)
    if since is not None:
        sql += " AND created_at > ?"
        args.append(since)
    if unread:
        sql += " AND read_at IS NULL"
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d.get("data") or "{}")
        except ValueError:
            d["data"] = {}
        d["desktop"] = bool(d["desktop"])
        out.append(d)
    return out


def unread_count() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM notifications WHERE read_at IS NULL").fetchone()[0]


def mark_read(ids: list[str] | None = None) -> int:
    with _conn() as conn:
        if ids:
            cur = conn.executemany("UPDATE notifications SET read_at = ? WHERE id = ? AND read_at IS NULL",
                                   [(time.time(), i) for i in ids])
        else:
            cur = conn.execute("UPDATE notifications SET read_at = ? WHERE read_at IS NULL", (time.time(),))
        return cur.rowcount


def clear() -> int:
    with _conn() as conn:
        return conn.execute("DELETE FROM notifications").rowcount


def set_push_status(event_type: str, status: str, error: str | None = None) -> None:
    """Mark the newest notification of this type with how the phone push went."""
    with _conn() as conn:
        conn.execute(
            "UPDATE notifications SET push_status = ?, push_error = ? WHERE id = (SELECT id FROM notifications"
            " WHERE event_type = ? ORDER BY created_at DESC LIMIT 1)",
            (status, (error or "")[:300] or None, event_type))
