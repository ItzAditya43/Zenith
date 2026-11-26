"""Background agent runs: queue a task, close the window, come back to a
finished (or waiting) run.

Each queued task runs the normal agent loop (agent_service.run_agent_turn)
as a backend task that doesn't depend on any browser connection. Its events
are kept in a persisted log, so the UI can show progress live or after the
fact. Approvals work exactly as in an interactive run: in manual or
semi-auto mode a risky step waits (up to the approval timeout) and the run
is marked "waiting" so the UI and a notification can ask for it. Runs go
one at a time per conversation, oldest first.

Statuses: queued → running ⇄ waiting → done | failed | cancelled |
interrupted (the backend stopped mid-run).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

LOG_LIMIT = 400          # events kept per run
TEXT_LIMIT = 4000        # chars kept per logged field
ACTIVE = ("queued", "running", "waiting")

_tasks: dict[str, asyncio.Task] = {}
_wakeup: asyncio.Event | None = None
_worker: asyncio.Task | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _row(r) -> dict:
    d = dict(r)
    try:
        d["log"] = json.loads(d.get("log") or "[]")
    except ValueError:
        d["log"] = []
    return d


def get_run(bid: str, with_log: bool = True) -> dict | None:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM background_runs WHERE id = ?", (bid,)).fetchone()
    if not r:
        return None
    d = _row(r)
    if not with_log:
        d.pop("log", None)
    return d


def list_runs(conversation_id: str | None = None, since: float | None = None, limit: int = 50) -> list[dict]:
    sql, args = "SELECT * FROM background_runs WHERE 1=1", []
    if conversation_id:
        sql += " AND conversation_id = ?"
        args.append(conversation_id)
    if since is not None:
        sql += " AND COALESCE(finished_at, started_at, created_at) > ?"
        args.append(since)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = _row(r)
        d["log_count"] = len(d.pop("log"))
        out.append(d)
    return out


def _update(bid: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as conn:
        conn.execute(f"UPDATE background_runs SET {cols} WHERE id = ?", (*fields.values(), bid))


def _trim(ev: dict) -> dict:
    out = {}
    for k, v in ev.items():
        if isinstance(v, str) and len(v) > TEXT_LIMIT:
            v = v[:TEXT_LIMIT] + " …"
        out[k] = v
    return out


def enqueue(conversation_id: str, prompt: str, model: str | None = None) -> dict:
    from app.db import storage

    if not storage.get_conversation(conversation_id):
        raise ValueError("Conversation not found.")
    if not prompt.strip():
        raise ValueError("Say what the task should do.")
    bid = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO background_runs (id, conversation_id, prompt, model, status, created_at) VALUES (?, ?, ?, ?, 'queued', ?)",
            (bid, conversation_id, prompt.strip(), model, time.time()),
        )
    _kick()
    return get_run(bid, with_log=False)  # type: ignore[return-value]


def cancel(bid: str) -> bool:
    run = get_run(bid, with_log=False)
    if not run or run["status"] not in ACTIVE:
        return False
    task = _tasks.get(bid)
    if task and not task.done():
        task.cancel()
    _update(bid, status="cancelled", finished_at=time.time())
    return True


def mark_reviewed(bid: str) -> bool:
    if not get_run(bid, with_log=False):
        return False
    _update(bid, reviewed_at=time.time())
    return True


def recover_interrupted() -> int:
    """At startup: anything still marked active was cut off by a restart."""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE background_runs SET status = 'interrupted', finished_at = ?, error = 'Zenith stopped while this was running.'"
            " WHERE status IN ('running', 'waiting')",
            (time.time(),),
        )
    return cur.rowcount


def _kick() -> None:
    global _wakeup, _worker, _loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _loop is not loop:  # a new event loop (server restart, tests): start fresh
        _loop, _wakeup, _worker = loop, asyncio.Event(), None
        _tasks.clear()
    assert _wakeup is not None
    _wakeup.set()
    if _worker is None or _worker.done():
        _worker = loop.create_task(_work_loop())


async def _work_loop() -> None:
    """Start queued runs, at most `agent_background_concurrency` at a time
    and never two in the same conversation."""
    global _wakeup
    assert _wakeup is not None
    while True:
        _wakeup.clear()
        limit = max(1, int(settings.get("agent_background_concurrency", 1)))
        running = {bid for bid, t in _tasks.items() if not t.done()}
        busy_convs = {get_run(b, with_log=False)["conversation_id"] for b in running if get_run(b, with_log=False)}
        with _conn() as conn:
            queued = [dict(r) for r in conn.execute(
                "SELECT id, conversation_id FROM background_runs WHERE status = 'queued' ORDER BY created_at ASC"
            ).fetchall()]
        for q in queued:
            if len(running) >= limit:
                break
            if q["conversation_id"] in busy_convs:
                continue
            task = asyncio.get_running_loop().create_task(_execute(q["id"]))
            _tasks[q["id"]] = task
            task.add_done_callback(lambda _t: _wakeup.set() if _wakeup else None)
            running.add(q["id"])
            busy_convs.add(q["conversation_id"])
        if not queued and not running:
            return
        await _wakeup.wait()


async def _notify(event: str, data: dict) -> None:
    try:
        from app.services import events, notify_service

        await events.emit(event, data)
        await notify_service.dispatch(event, data)
    except Exception as exc:  # noqa: BLE001
        log.debug("background.notify_failed", error=str(exc))


async def _execute(bid: str) -> None:
    from app.core.rate_limit import conversation_lock
    from app.db import storage
    from app.services import agent_service

    run = get_run(bid, with_log=False)
    if not run or run["status"] != "queued":
        return
    cid, prompt = run["conversation_id"], run["prompt"]
    events: list[dict] = []
    last_flush = 0.0
    tokens: list[str] = []

    def record(ev: dict, force: bool = False) -> None:
        nonlocal last_flush
        events.append(_trim({**ev, "t": round(time.time(), 2)}))
        del events[:-LOG_LIMIT]
        if force or time.time() - last_flush > 1.0:
            last_flush = time.time()
            _update(bid, log=json.dumps(events))

    _update(bid, status="running", started_at=time.time())
    status, summary, error = "failed", None, None
    try:
        async with conversation_lock(cid):
            history_last_model = next((m["model"] for m in reversed(storage.get_messages(cid)) if m.get("model")), None)
            async for ev in agent_service.run_agent_turn(cid, prompt, [], history_last_model=history_last_model,
                                                         model_override=run.get("model")):
                et = ev.get("type")
                if et == "token":
                    tokens.append(ev.get("text") or "")
                    continue
                if et == "tool_pending":
                    _update(bid, status="waiting")
                    record(ev, force=True)
                    await _notify("agent_run_needs_approval", {"id": bid, "prompt": prompt[:200],
                                                               "detail": f"{ev.get('tool')}: {str(ev.get('args'))[:160]}"})
                    continue
                if et in ("tool_result", "tool_denied"):
                    _update(bid, status="running")
                if et == "done":
                    full = (ev.get("full_text") or "".join(tokens)).strip()
                    if not full:
                        raise RuntimeError("The model returned an empty reply.")
                    storage.add_message(cid, "assistant", full, model=ev.get("model"), route_role=ev.get("role"),
                                        route_reason=ev.get("reason"), parent_id=ev.get("parent_id"))
                    _update(bid, run_id=ev.get("parent_id"))
                    record({"type": "done", "model": ev.get("model")}, force=True)
                    status, summary = "done", full[:600]
                    break
                if et == "error":
                    raise RuntimeError(ev.get("message") or "The run failed.")
                if et == "route":
                    _update(bid, model=ev.get("model"))
                record(ev)
        try:
            from app.services import memory_service, rag_service

            if summary:
                await asyncio.to_thread(rag_service.index_message, cid, "assistant", summary)
            asyncio.get_running_loop().create_task(memory_service.extract_from_text(prompt, cid))
        except Exception as exc:  # noqa: BLE001
            log.debug("background.housekeeping_failed", error=str(exc))
    except asyncio.CancelledError:
        status, error = "cancelled", "Cancelled."
        record({"type": "cancelled"}, force=True)
    except Exception as exc:  # noqa: BLE001
        status, error = "failed", str(exc) or exc.__class__.__name__
        record({"type": "error", "message": error}, force=True)
        log.warning("background.run_failed", id=bid, error=error)
    finally:
        _update(bid, status=status, finished_at=time.time(), summary=summary, error=error, log=json.dumps(events))
        _tasks.pop(bid, None)
    await _notify("agent_run_finished", {"id": bid, "status": status, "prompt": prompt[:200],
                                          "summary": (summary or error or "")[:300]})


# ---- run review (any agent run, background or interactive) -------------------------

def review(run_id: str) -> dict:
    """Everything one agent run did, for the review screen: changed files
    with diffs, commands and checks with their output, and every other
    tool call, in order."""
    with _conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, tool, args, risk, status, result, diff, created_at, resolved_at, conversation_id"
            " FROM tool_calls WHERE run_id = ? ORDER BY created_at ASC", (run_id,)
        ).fetchall()]
        msg = conn.execute("SELECT * FROM messages WHERE parent_id = ? AND role = 'assistant' ORDER BY created_at DESC LIMIT 1",
                           (run_id,)).fetchone()
        prompt = conn.execute("SELECT content FROM messages WHERE id = ?", (run_id,)).fetchone()
        bg = conn.execute("SELECT id, status, reviewed_at FROM background_runs WHERE run_id = ?", (run_id,)).fetchone()
    files: dict[str, dict] = {}
    commands, activity = [], []
    for r in rows:
        try:
            args = json.loads(r["args"]) if isinstance(r["args"], str) else (r["args"] or {})
        except ValueError:
            args = {}
        item = {"id": r["id"], "tool": r["tool"], "status": r["status"], "risk": r["risk"],
                "args": args, "result": (r["result"] or "")[:TEXT_LIMIT], "at": r["created_at"]}
        activity.append(item)
        if r["tool"] in ("edit_file", "write_file"):
            path = args.get("path") or "?"
            f = files.setdefault(path, {"path": path, "diffs": [], "calls": [], "applied": False, "reverted": False})
            if r["diff"]:
                f["diffs"].append(r["diff"])
            f["calls"].append(r["id"])
            f["applied"] = f["applied"] or r["status"] == "executed"
            f["reverted"] = r["status"] == "reverted"
        elif r["tool"] in ("bash", "run_checks", "shell_start", "git"):
            commands.append({**item, "command": args.get("command") or args.get("cmd") or " ".join(map(str, args.get("args", []))) or r["tool"],
                             "is_check": r["tool"] == "run_checks"})
    return {
        "run_id": run_id,
        "prompt": prompt["content"] if prompt else "",
        "reply": dict(msg)["content"] if msg else "",
        "files": list(files.values()),
        "commands": commands,
        "activity": activity,
        "counts": {
            "files": len(files),
            "edits_applied": sum(1 for a in activity if a["tool"] in ("edit_file", "write_file") and a["status"] == "executed"),
            "denied": sum(1 for a in activity if a["status"] in ("denied", "rejected")),
            "pending": sum(1 for a in activity if a["status"] == "pending"),
        },
        "background": dict(bg) if bg else None,
    }
