"""Scheduled/recurring turns: "every morning, research X and summarize"
without touching the keyboard. A lightweight interval scheduler on
purpose — one number (minutes), not cron syntax, which is plenty for a
personal tool and needs no parser.

Deliberately restricted to "chat" and "research" modes, never "agent" —
an unattended cron job running shell commands with nobody there to
approve/deny is a real escalation beyond what agent mode's approval
gates are designed for. If you want a scheduled turn to take actions,
have it write a report and review it yourself before acting on it.

Each schedule gets one persistent conversation (created on its first
run, reused after) so a running log builds up you can scroll back
through, rather than a new orphaned conversation every time.
"""
from __future__ import annotations

import time
import uuid

from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

ALLOWED_MODES = {"chat", "research"}


def list_schedules() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM schedules ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]


def get_schedule(schedule_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        return dict(row) if row else None


def create_schedule(name: str, prompt: str, mode: str, interval_minutes: int) -> dict:
    if mode not in ALLOWED_MODES:
        raise ValueError(f"mode must be one of {sorted(ALLOWED_MODES)}, got {mode!r}")
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be at least 1")
    sid = str(uuid.uuid4())
    now = time.time()
    next_run = now + interval_minutes * 60
    with _conn() as conn:
        conn.execute(
            """INSERT INTO schedules
               (id, name, prompt, mode, interval_minutes, conversation_id, enabled,
                last_run_at, next_run_at, created_at)
               VALUES (?, ?, ?, ?, ?, NULL, 1, NULL, ?, ?)""",
            (sid, name.strip(), prompt.strip(), mode, interval_minutes, next_run, now),
        )
    return {
        "id": sid, "name": name.strip(), "prompt": prompt.strip(), "mode": mode,
        "interval_minutes": interval_minutes, "conversation_id": None, "enabled": 1,
        "last_run_at": None, "next_run_at": next_run, "created_at": now,
    }


def delete_schedule(schedule_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM schedule_runs WHERE schedule_id = ?", (schedule_id,))
        conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))


def set_enabled(schedule_id: str, enabled: bool) -> None:
    with _conn() as conn:
        conn.execute("UPDATE schedules SET enabled = ? WHERE id = ?", (1 if enabled else 0, schedule_id))


def list_runs(schedule_id: str, limit: int = 20) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule_runs WHERE schedule_id = ? ORDER BY started_at DESC LIMIT ?",
            (schedule_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_recent_runs(since: float, limit: int = 20) -> list[dict]:
    """Completed runs across all schedules that finished after `since`,
    with the schedule's name joined in. Powers the frontend's background
    desktop-notification poll — it asks 'what finished since I last checked'."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT r.id, r.schedule_id, r.finished_at, r.status, r.summary,
                   s.name AS schedule_name, s.conversation_id
            FROM schedule_runs r
            JOIN schedules s ON s.id = r.schedule_id
            WHERE r.finished_at IS NOT NULL AND r.finished_at > ?
            ORDER BY r.finished_at DESC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()
        return [dict(r) for r in rows]


async def _ensure_conversation(schedule: dict) -> str:
    from app.db import storage

    if schedule.get("conversation_id"):
        return schedule["conversation_id"]
    conv = storage.create_conversation(f"[Scheduled] {schedule['name']}")
    with _conn() as conn:
        conn.execute(
            "UPDATE schedules SET conversation_id = ? WHERE id = ?", (conv["id"], schedule["id"])
        )
    return conv["id"]


async def run_schedule(schedule: dict) -> dict:
    """Executes one scheduled turn end to end (not streamed — nobody's
    watching). Returns the schedule_runs row. Never raises: failures are
    captured in the run record so a bad schedule doesn't take the
    scanner loop down."""
    run_id = str(uuid.uuid4())
    started = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO schedule_runs (id, schedule_id, started_at, status) VALUES (?, ?, ?, 'running')",
            (run_id, schedule["id"], started),
        )

    try:
        conversation_id = await _ensure_conversation(schedule)
        full_text = ""

        if schedule["mode"] == "research":
            from app.services import research_service
            async for ev in research_service.run_deep_research(conversation_id, schedule["prompt"], []):
                if ev.get("type") == "done":
                    full_text = ev["full_text"]
        else:
            from app.services.orchestrator import run_turn
            from app.db import storage as _storage
            decision, stream, _sources, assistant_parent_id = await run_turn(
                conversation_id, schedule["prompt"], [],
            )
            collected = []
            async for piece in stream:
                collected.append(piece)
            full_text = "".join(collected)
            if full_text.strip():
                _storage.add_message(
                    conversation_id, "assistant", full_text,
                    model=decision.model, route_role=decision.role, route_reason=decision.reason,
                    parent_id=assistant_parent_id,
                )

        finished = time.time()
        with _conn() as conn:
            conn.execute(
                "UPDATE schedule_runs SET finished_at = ?, status = 'success', summary = ? WHERE id = ?",
                (finished, full_text[:500], run_id),
            )
            conn.execute(
                "UPDATE schedules SET last_run_at = ?, next_run_at = ? WHERE id = ?",
                (finished, finished + schedule["interval_minutes"] * 60, schedule["id"]),
            )
        log.info("schedule.run_succeeded", schedule_id=schedule["id"], name=schedule["name"])
        return {"id": run_id, "status": "success", "summary": full_text[:500]}
    except Exception as exc:
        finished = time.time()
        log.warning("schedule.run_failed", schedule_id=schedule["id"], error=str(exc))
        with _conn() as conn:
            conn.execute(
                "UPDATE schedule_runs SET finished_at = ?, status = 'error', error = ? WHERE id = ?",
                (finished, str(exc)[:500], run_id),
            )
            conn.execute(
                "UPDATE schedules SET last_run_at = ?, next_run_at = ? WHERE id = ?",
                (finished, finished + schedule["interval_minutes"] * 60, schedule["id"]),
            )
        return {"id": run_id, "status": "error", "error": str(exc)}


async def run_due_schedules() -> None:
    now = time.time()
    for schedule in list_schedules():
        if not schedule["enabled"]:
            continue
        if schedule["next_run_at"] is not None and schedule["next_run_at"] > now:
            continue
        await run_schedule(schedule)
