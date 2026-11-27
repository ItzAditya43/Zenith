"""Scheduled/recurring turns: "every morning, research X and summarize"
without touching the keyboard. Three kinds, no cron syntax:

  * interval — every N minutes (the advanced option)
  * daily    — at HH:MM in a named timezone
  * weekly   — at HH:MM on chosen weekdays (0=Mon … 6=Sun)

Wall-clock schedules are computed with zoneinfo, so 08:00 stays 08:00
across daylight-saving changes. If the computer was asleep through one or
more runs, the schedule runs once when it wakes (never a burst) and the
skipped ones are counted as missed. Three failures in a row raise a
`schedule_failing` notification; five pause the schedule.

Deleting a schedule keeps its run history and conversation.

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

import datetime as dt
import re
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

ALLOWED_MODES = {"chat", "research"}
KINDS = {"interval", "daily", "weekly"}
NOTIFY_AFTER_FAILURES = 3
PAUSE_AFTER_FAILURES = 5
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _zone(name: str | None) -> dt.tzinfo:
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return dt.datetime.now().astimezone().tzinfo or dt.UTC


def next_run_after(schedule: dict, after: float) -> float:
    """The first run time strictly after `after` (unix seconds)."""
    kind = schedule.get("kind") or "interval"
    if kind == "interval":
        return after + int(schedule["interval_minutes"]) * 60
    tz = _zone(schedule.get("timezone"))
    hh, mm = (int(x) for x in (schedule.get("time_of_day") or "09:00").split(":"))
    days = _weekdays(schedule) if kind == "weekly" else list(range(7))
    local = dt.datetime.fromtimestamp(after, tz)
    for offset in range(0, 8):
        day = (local + dt.timedelta(days=offset)).date()
        if day.weekday() not in days:
            continue
        cand = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
        # A time that doesn't exist on a DST spring-forward day folds forward.
        ts = cand.timestamp()
        if ts > after:
            return ts
    return after + 7 * 86400


def _weekdays(schedule: dict) -> list[int]:
    raw = schedule.get("weekdays") or ""
    days = [int(x) for x in str(raw).split(",") if x.strip().isdigit() and 0 <= int(x) <= 6]
    return days or [0]


def describe(schedule: dict) -> str:
    kind = schedule.get("kind") or "interval"
    if kind == "interval":
        m = int(schedule["interval_minutes"])
        return f"Every {m} min" if m < 60 else f"Every {m // 60} h" + (f" {m % 60} min" if m % 60 else "")
    tz = schedule.get("timezone") or "local time"
    if kind == "daily":
        return f"Daily at {schedule.get('time_of_day')} ({tz})"
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return f"{', '.join(names[d] for d in _weekdays(schedule))} at {schedule.get('time_of_day')} ({tz})"


def _decorate(d: dict) -> dict:
    d["description"] = describe(d)
    return d


def list_schedules() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM schedules WHERE deleted_at IS NULL ORDER BY created_at ASC").fetchall()
        return [_decorate(dict(r)) for r in rows]


def get_schedule(schedule_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE id = ? AND deleted_at IS NULL", (schedule_id,)).fetchone()
        return _decorate(dict(row)) if row else None


CHECKLIST_NOTE = (
    "\n\nEnd your reply with any follow-up tasks as a checklist, one per line, like:\n"
    "- [ ] Do the thing\nWrite \"- [ ] none\" if there's nothing to do."
)


def checklist_items(text: str) -> list[str]:
    items = [m.strip() for m in re.findall(r"^\s*[-*]\s*\[ \]\s*(.+)$", text or "", re.M)]
    return [i for i in items if i and i.lower() not in ("none", "nothing", "n/a")][:10]


async def _todos_from_run(schedule: dict, full_text: str) -> list[str]:
    """Turn a run's result into to-dos per the schedule's todo_mode."""
    from app.services.automation_service import add_todo_once

    mode = schedule.get("todo_mode") or "none"
    if mode == "none" or not full_text.strip():
        return []
    texts = checklist_items(full_text) if mode == "checklist" else [
        f"{schedule['name']}: " + next((ln.strip(" #*-") for ln in full_text.splitlines() if ln.strip(" #*-")), "")[:200]
    ]
    added = []
    for t in texts:
        if await add_todo_once(t, source=f"schedule:{schedule['name']}"):
            added.append(t)
    return added


def _validate_timing(kind: str, interval_minutes: int, time_of_day: str | None, weekdays: list[int] | None,
                     timezone: str | None) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    if kind == "interval" and interval_minutes < 1:
        raise ValueError("interval_minutes must be at least 1")
    if kind != "interval" and not (time_of_day and _HHMM.match(time_of_day)):
        raise ValueError("time_of_day must be HH:MM (24-hour)")
    if kind == "weekly" and not weekdays:
        raise ValueError("Pick at least one weekday.")
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown timezone {timezone!r}") from None


def create_schedule(name: str, prompt: str, mode: str, interval_minutes: int, todo_mode: str = "none", *,
                    kind: str = "interval", time_of_day: str | None = None, weekdays: list[int] | None = None,
                    timezone: str | None = None) -> dict:
    if mode not in ALLOWED_MODES:
        raise ValueError(f"mode must be one of {sorted(ALLOWED_MODES)}, got {mode!r}")
    _validate_timing(kind, interval_minutes, time_of_day, weekdays, timezone)
    sid = str(uuid.uuid4())
    now = time.time()
    row = {
        "id": sid, "name": name.strip(), "prompt": prompt.strip(), "mode": mode,
        "interval_minutes": max(1, interval_minutes), "conversation_id": None, "enabled": 1,
        "last_run_at": None, "created_at": now,
        "todo_mode": todo_mode if todo_mode in ("none", "add", "checklist") else "none",
        "kind": kind, "time_of_day": time_of_day if kind != "interval" else None,
        "weekdays": ",".join(str(d) for d in sorted(set(weekdays or []))) if kind == "weekly" else None,
        "timezone": timezone if kind != "interval" else None,
        "consecutive_failures": 0, "missed_runs": 0, "deleted_at": None,
    }
    row["next_run_at"] = next_run_after(row, now)
    with _conn() as conn:
        conn.execute(
            """INSERT INTO schedules
               (id, name, prompt, mode, interval_minutes, conversation_id, enabled,
                last_run_at, next_run_at, created_at, todo_mode, kind, time_of_day, weekdays, timezone)
               VALUES (?, ?, ?, ?, ?, NULL, 1, NULL, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, row["name"], row["prompt"], mode, row["interval_minutes"], row["next_run_at"], now,
             row["todo_mode"], kind, row["time_of_day"], row["weekdays"], row["timezone"]),
        )
    return _decorate(row)


def update_timing(schedule_id: str, *, kind: str, interval_minutes: int, time_of_day: str | None,
                  weekdays: list[int] | None, timezone: str | None) -> dict | None:
    _validate_timing(kind, interval_minutes, time_of_day, weekdays, timezone)
    s = get_schedule(schedule_id)
    if not s:
        return None
    s.update(kind=kind, interval_minutes=max(1, interval_minutes),
             time_of_day=time_of_day if kind != "interval" else None,
             weekdays=",".join(str(d) for d in sorted(set(weekdays or []))) if kind == "weekly" else None,
             timezone=timezone if kind != "interval" else None)
    s["next_run_at"] = next_run_after(s, time.time())
    with _conn() as conn:
        conn.execute(
            "UPDATE schedules SET kind = ?, interval_minutes = ?, time_of_day = ?, weekdays = ?, timezone = ?,"
            " next_run_at = ? WHERE id = ?",
            (s["kind"], s["interval_minutes"], s["time_of_day"], s["weekdays"], s["timezone"], s["next_run_at"],
             schedule_id),
        )
    return _decorate(s)


def delete_schedule(schedule_id: str) -> None:
    """Soft delete: the schedule stops and disappears from the list; its
    runs and conversation stay."""
    with _conn() as conn:
        conn.execute("UPDATE schedules SET deleted_at = ?, enabled = 0 WHERE id = ?", (time.time(), schedule_id))


def set_enabled(schedule_id: str, enabled: bool) -> None:
    with _conn() as conn:
        if enabled:
            s = get_schedule(schedule_id)
            nxt = next_run_after(s, time.time()) if s else None
            conn.execute("UPDATE schedules SET enabled = 1, consecutive_failures = 0, next_run_at = ? WHERE id = ?",
                         (nxt, schedule_id))
        else:
            conn.execute("UPDATE schedules SET enabled = 0 WHERE id = ?", (schedule_id,))


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
        model = None
        partial = False
        prompt = schedule["prompt"] + (CHECKLIST_NOTE if schedule.get("todo_mode") == "checklist" else "")

        if schedule["mode"] == "research":
            from app.services import research_service
            got_done = False
            async for ev in research_service.run_deep_research(conversation_id, prompt, []):
                if ev.get("type") == "done":
                    full_text = ev["full_text"]
                    got_done = True
                    model = ev.get("model") or model
            partial = not got_done
        else:
            from app.db import storage as _storage
            from app.services.orchestrator import run_turn
            decision, stream, _sources, assistant_parent_id = await run_turn(
                conversation_id, prompt, [],
            )
            collected = []
            async for piece in stream:
                collected.append(piece)
            full_text = "".join(collected)
            model = decision.model
            if full_text.strip():
                _storage.add_message(
                    conversation_id, "assistant", full_text,
                    model=decision.model, route_role=decision.role, route_reason=decision.reason,
                    parent_id=assistant_parent_id,
                )

        added_todos = []
        try:
            added_todos = await _todos_from_run(schedule, full_text)
        except Exception as exc:
            log.warning("schedule.todo_add_failed", error=str(exc))
        summary = full_text[:500] + (f"\n\nAdded {len(added_todos)} to-do(s): " + "; ".join(added_todos) if added_todos else "")
        finished = time.time()
        status = "partial" if partial or not full_text.strip() else "success"
        if status == "partial":
            summary = "Partial result — the run ended before finishing.\n\n" + summary
        with _conn() as conn:
            conn.execute(
                "UPDATE schedule_runs SET finished_at = ?, status = ?, summary = ?, model = ? WHERE id = ?",
                (finished, status, summary[:1500], model, run_id),
            )
            conn.execute(
                "UPDATE schedules SET last_run_at = ?, next_run_at = ?, consecutive_failures = 0 WHERE id = ?",
                (finished, next_run_after(schedule, finished), schedule["id"]),
            )
        log.info("schedule.run_succeeded", schedule_id=schedule["id"], name=schedule["name"])
        try:
            from app.services import events
            await events.emit("schedule_completed", {
                "schedule_id": schedule["id"], "name": schedule["name"],
                "summary": full_text[:500], "todos_added": added_todos,
                "result": (f"Added {len(added_todos)} to-do(s). " if added_todos else "") + full_text[:300],
            })
        except Exception as exc:
            log.debug("schedule.event_emit_failed", error=str(exc))
        return {"id": run_id, "status": status, "summary": summary[:1500], "todos_added": added_todos, "model": model}
    except Exception as exc:
        finished = time.time()
        log.warning("schedule.run_failed", schedule_id=schedule["id"], error=str(exc))
        with _conn() as conn:
            conn.execute(
                "UPDATE schedule_runs SET finished_at = ?, status = 'error', error = ? WHERE id = ?",
                (finished, str(exc)[:500], run_id),
            )
            conn.execute(
                "UPDATE schedules SET last_run_at = ?, next_run_at = ?, consecutive_failures = consecutive_failures + 1"
                " WHERE id = ?",
                (finished, next_run_after(schedule, finished), schedule["id"]),
            )
            fails = conn.execute("SELECT consecutive_failures FROM schedules WHERE id = ?",
                                 (schedule["id"],)).fetchone()[0]
            if fails >= PAUSE_AFTER_FAILURES:
                conn.execute("UPDATE schedules SET enabled = 0 WHERE id = ?", (schedule["id"],))
        if fails >= NOTIFY_AFTER_FAILURES:
            try:
                from app.services import events
                await events.emit("schedule_failing", {
                    "schedule_id": schedule["id"], "name": schedule["name"], "failures": fails,
                    "paused": fails >= PAUSE_AFTER_FAILURES, "error": str(exc)[:300],
                    "result": f"{schedule['name']} failed {fails} times in a row"
                              + (" and was paused." if fails >= PAUSE_AFTER_FAILURES else ".") + f" Last error: {str(exc)[:200]}",
                })
            except Exception as e2:  # noqa: BLE001
                log.debug("schedule.event_emit_failed", error=str(e2))
        return {"id": run_id, "status": "error", "error": str(exc)}


async def run_due_schedules() -> None:
    now = time.time()
    for schedule in list_schedules():
        if not schedule["enabled"]:
            continue
        if schedule["next_run_at"] is not None and schedule["next_run_at"] > now:
            continue
        missed = count_missed(schedule, now)
        if missed:
            with _conn() as conn:
                conn.execute("UPDATE schedules SET missed_runs = missed_runs + ? WHERE id = ?", (missed, schedule["id"]))
        await run_schedule(schedule)


def count_missed(schedule: dict, now: float) -> int:
    """Runs that came due while nothing was running (asleep / app closed),
    beyond the one we're about to do. Capped so a long holiday doesn't loop."""
    due = schedule.get("next_run_at")
    if due is None:
        return 0
    n, t = 0, next_run_after(schedule, due)
    while t <= now and n < 1000:
        n += 1
        t = next_run_after(schedule, t)
    return n
