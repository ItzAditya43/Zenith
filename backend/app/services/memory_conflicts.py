"""Resolving flagged memory contradictions — keep both, keep one, merge
into one statement, or dismiss — with undo.

Nothing is deleted: "keep one" turns the other memory off, and "merge"
rewrites the first and turns the second off, so undo can put back exactly
what was there. Each conflict is shown with its evidence: where each
memory came from (source chat), when it was saved and last changed, and a
suggestion (the more recently confirmed one is usually current).
"""
from __future__ import annotations

import json
import time

from app.db.storage import _conn
from app.services import memory_service

ACTIONS = {"keep_both", "keep_a", "keep_b", "merge", "dismiss"}


def _evidence(mem: dict) -> dict:
    with _conn() as conn:
        title = None
        if mem.get("source_conversation_id"):
            r = conn.execute("SELECT title FROM conversations WHERE id = ?", (mem["source_conversation_id"],)).fetchone()
            title = r["title"] if r else None
    return {**mem, "source_title": title}


def suggest(a: dict, b: dict) -> dict:
    ta, tb = a.get("updated_at") or a.get("created_at") or 0, b.get("updated_at") or b.get("created_at") or 0
    if abs(ta - tb) < 60:
        return {"action": "keep_both", "why": "Saved at about the same time — check which is right."}
    newer = "keep_a" if ta > tb else "keep_b"
    return {"action": newer, "why": "The newer memory is usually the current one."}


def enrich(conflict: dict) -> dict | None:
    a = memory_service.get_memory(conflict["memory_id_a"])
    b = memory_service.get_memory(conflict["memory_id_b"])
    if not a or not b:
        return None
    ea, eb = _evidence(a), _evidence(b)
    return {**conflict, "memory_a": ea, "memory_b": eb, "suggestion": suggest(ea, eb)}


def _set_enabled(memory_id: str, enabled: bool) -> None:
    with _conn() as conn:
        conn.execute("UPDATE memories SET enabled = ?, updated_at = ? WHERE id = ?",
                     (1 if enabled else 0, time.time(), memory_id))


def resolve(conflict_id: str, action: str, merged_text: str | None = None) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {sorted(ACTIONS)}")
    with _conn() as conn:
        c = conn.execute("SELECT * FROM memory_conflicts WHERE id = ?", (conflict_id,)).fetchone()
    if not c or c["resolved"]:
        return {"ok": True, "action": None}  # idempotent, like the other resolve endpoints
    c = dict(c)
    a = memory_service.get_memory(c["memory_id_a"])
    b = memory_service.get_memory(c["memory_id_b"])
    if not a or not b:
        raise LookupError("One of these memories no longer exists.")
    undo: dict = {"enable": [], "disable": [], "content": {}}
    if action == "keep_a":
        _set_enabled(b["id"], False)
        if b["enabled"]:
            undo["enable"].append(b["id"])
    elif action == "keep_b":
        _set_enabled(a["id"], False)
        if a["enabled"]:
            undo["enable"].append(a["id"])
    elif action == "merge":
        text = (merged_text or "").strip()
        if not text:
            raise ValueError("Write the combined memory first.")
        undo["content"][a["id"]] = a["content"]
        memory_service.update_memory(a["id"], content=text)
        _set_enabled(b["id"], False)
        if b["enabled"]:
            undo["enable"].append(b["id"])
    with _conn() as conn:
        conn.execute("UPDATE memory_conflicts SET resolved = 1, resolution = ?, resolved_at = ?, undo = ? WHERE id = ?",
                     (action, time.time(), json.dumps(undo), conflict_id))
    return {"ok": True, "action": action}


def undo(conflict_id: str) -> dict:
    with _conn() as conn:
        c = conn.execute("SELECT * FROM memory_conflicts WHERE id = ?", (conflict_id,)).fetchone()
    if not c or not c["resolved"]:
        raise LookupError("Nothing to undo.")
    data = json.loads(c["undo"] or "{}")
    for mid, content in (data.get("content") or {}).items():
        if memory_service.get_memory(mid):
            memory_service.update_memory(mid, content=content)
    for mid in data.get("enable") or []:
        _set_enabled(mid, True)
    for mid in data.get("disable") or []:
        _set_enabled(mid, False)
    with _conn() as conn:
        conn.execute("UPDATE memory_conflicts SET resolved = 0, resolution = NULL, resolved_at = NULL, undo = NULL"
                     " WHERE id = ?", (conflict_id,))
    return {"ok": True}


def recent_resolved(limit: int = 10) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM memory_conflicts WHERE resolved = 1 AND resolution IS NOT NULL"
                            " ORDER BY resolved_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        e = enrich(dict(r))
        if e:
            out.append(e)
    return out
