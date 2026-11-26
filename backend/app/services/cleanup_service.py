"""Knowledge cleanup: find what's duplicated, stale or orphaned in memory
and the retrieval index, and fix it only with the user's say-so.

`scan()` proposes changes, each with the evidence for it (where the item
came from, when it was last used or indexed). Nothing changes until the
user applies a selection; `apply()` records exactly what it removed or
changed so `undo()` can put it back.

Proposal kinds
  orphan_source      index entries whose file, chat, attachment or memory is gone → remove from index
  changed_file       a watched file changed after it was indexed → reindex it
  duplicate_document the same text indexed under two documents → remove the later copy
  duplicate_memory   two memories saying (nearly) the same thing → merge into one
  stale_memory       a memory unused for months → turn it off
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

STALE_DAYS = 120
DUP_THRESHOLD = 0.7


def _pid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:14]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1}


def _similar(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    inter = len(wa & wb)
    return max(inter / len(wa | wb), inter / min(len(wa), len(wb)) * 0.9)


def _rag():
    from app.services import rag_service

    rag_service._ensure_table()  # noqa: SLF001
    return rag_service


def _index_rows() -> list[dict]:
    rag = _rag()
    cur = rag._conn().cursor()  # noqa: SLF001
    cur.execute("SELECT source_kind, source_id, MAX(conversation_id), MAX(created_at), COUNT(*), "
                "GROUP_CONCAT(text, char(31)) FROM chunks GROUP BY source_kind, source_id")
    return [{"kind": k, "id": i, "conversation_id": c, "indexed_at": t, "chunks": n, "text": x or ""}
            for k, i, c, t, n, x in cur.fetchall()]


def scan() -> list[dict]:
    from app.db import storage
    from app.services import attachments as att_service
    from app.services import memory_service

    out: list[dict] = []
    now = time.time()
    rows = _index_rows()
    memories = {m["id"]: m for m in memory_service.list_memories()}
    conv_ids = {c["id"] for c in storage.list_conversations()}

    seen_text: dict[str, dict] = {}
    for r in rows:
        reason = None
        if r["kind"] == "folder" and not os.path.exists(r["id"]):
            reason = "the file no longer exists"
        elif r["kind"] == "document" and att_service.get(r["id"]) is None:
            reason = "the attachment was deleted"
        elif r["kind"] == "memory" and r["id"] not in memories:
            reason = "the memory was forgotten"
        elif r["kind"] == "message" and r["conversation_id"] and r["conversation_id"] not in conv_ids:
            reason = "the chat was deleted"
        if reason:
            out.append({"id": _pid("orphan", r["kind"], r["id"]), "kind": "orphan_source", "action": "Remove from the index",
                        "title": os.path.basename(r["id"]) if r["kind"] == "folder" else f"{r['kind']} {r['id'][:12]}",
                        "detail": f"{r['chunks']} indexed passage{'s' if r['chunks'] != 1 else ''}; {reason}.",
                        "targets": [{"kind": r["kind"], "id": r["id"]}]})
            continue
        if r["kind"] == "folder":
            try:
                if os.path.getmtime(r["id"]) > (r["indexed_at"] or 0) + 5:
                    out.append({"id": _pid("changed", r["id"], str(int(os.path.getmtime(r["id"])))), "kind": "changed_file",
                                "action": "Reindex", "title": os.path.basename(r["id"]),
                                "detail": f"Changed after it was indexed ({r['id']}).", "targets": [{"kind": "folder", "id": r["id"]}]})
            except OSError:
                pass
        if r["kind"] == "document" and len(r["text"]) > 200:
            h = hashlib.sha1(r["text"].encode()).hexdigest()
            first = seen_text.get(h)
            if first:
                keep, drop = sorted([first, r], key=lambda x: x["indexed_at"] or 0)
                a, b = att_service.get(keep["id"]), att_service.get(drop["id"])
                out.append({"id": _pid("dupdoc", keep["id"], drop["id"]), "kind": "duplicate_document", "action": "Remove the later copy",
                            "title": f"{getattr(b, 'filename', drop['id'])}",
                            "detail": f"Same text as “{getattr(a, 'filename', keep['id'])}”, indexed earlier.",
                            "targets": [{"kind": "document", "id": drop["id"]}], "keep": keep["id"]})
            else:
                seen_text[h] = r

    active = [m for m in memories.values() if m["enabled"] and (m.get("status") or "active") == "active"]
    paired: set[str] = set()
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if a["id"] in paired or b["id"] in paired:
                continue
            if (a.get("scope") or "global") != (b.get("scope") or "global"):
                continue
            if _similar(a["content"], b["content"]) >= DUP_THRESHOLD:
                keep = a if len(a["content"]) >= len(b["content"]) else b
                paired.update({a["id"], b["id"]})
                out.append({"id": _pid("dupmem", *sorted([a["id"], b["id"]])), "kind": "duplicate_memory",
                            "action": "Merge into one", "title": keep["content"],
                            "detail": f"“{a['content']}” and “{b['content']}” say the same thing.",
                            "targets": [{"kind": "memory", "id": a["id"]}, {"kind": "memory", "id": b["id"]}],
                            "merged": keep["content"]})
    cutoff = now - STALE_DAYS * 86400
    for m in active:
        last = m.get("last_used_at") or 0
        if m["created_at"] < cutoff and last < cutoff and m["id"] not in paired:
            used = f"last used {time.strftime('%Y-%m-%d', time.localtime(last))}" if last else "never used"
            out.append({"id": _pid("stale", m["id"], str(int(last))), "kind": "stale_memory", "action": "Turn off",
                        "title": m["content"], "detail": f"Saved {time.strftime('%Y-%m-%d', time.localtime(m['created_at']))}, {used}.",
                        "targets": [{"kind": "memory", "id": m["id"]}]})
    return out


def _chunk_rows(kind: str, sid: str) -> list[dict]:
    cur = _rag()._conn().cursor()  # noqa: SLF001
    cur.execute("SELECT source_kind, source_id, conversation_id, chunk_index, text, created_at FROM chunks "
                "WHERE source_kind = ? AND source_id = ?", (kind, sid))
    return [dict(zip(("source_kind", "source_id", "conversation_id", "chunk_index", "text", "created_at"), r))
            for r in cur.fetchall()]


def apply(ids: list[str]) -> dict:
    """Apply the chosen proposals (re-checked now, so a stale id does
    nothing). Returns {batch_id, applied, skipped}."""
    from app.services import memory_service

    wanted = set(ids)
    props = [p for p in scan() if p["id"] in wanted]
    rag = _rag()
    undo: list[dict] = []
    applied = []
    for p in props:
        try:
            if p["kind"] in ("orphan_source", "duplicate_document"):
                for t in p["targets"]:
                    undo.append({"op": "restore_chunks", "rows": _chunk_rows(t["kind"], t["id"])})
                    rag.delete_source(t["id"], t["kind"])
            elif p["kind"] == "changed_file":
                from app.services import document_service

                path = p["targets"][0]["id"]
                text = document_service.extract_text(path)
                if text and text.strip():
                    rag.index_folder_file(path, text, "")
            elif p["kind"] == "duplicate_memory":
                rows = [memory_service.get_memory(t["id"]) for t in p["targets"]]
                rows = [r for r in rows if r]
                undo.append({"op": "restore_memories", "rows": rows})
                merged = memory_service.merge_memories([r["id"] for r in rows], p["merged"])
                undo.append({"op": "delete_memory", "id": merged["id"]})
            elif p["kind"] == "stale_memory":
                mid = p["targets"][0]["id"]
                undo.append({"op": "enable_memory", "id": mid})
                memory_service.set_enabled(mid, False)
            applied.append({"id": p["id"], "kind": p["kind"], "title": p["title"], "action": p["action"]})
        except Exception as exc:  # noqa: BLE001 — one bad item shouldn't stop the rest
            log.warning("cleanup.apply_failed", kind=p["kind"], error=str(exc))
    batch = uuid.uuid4().hex[:12]
    if applied:
        with _conn() as conn:
            conn.execute("INSERT INTO cleanup_log (id, applied, undo, created_at) VALUES (?, ?, ?, ?)",
                         (batch, json.dumps(applied), json.dumps(undo, default=str), time.time()))
    return {"batch_id": batch if applied else None, "applied": applied, "skipped": len(wanted) - len(applied)}


def history(limit: int = 20) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT id, applied, created_at, undone_at FROM cleanup_log ORDER BY created_at DESC LIMIT ?",
                            (limit,)).fetchall()
    return [{"id": r["id"], "applied": json.loads(r["applied"]), "created_at": r["created_at"], "undone_at": r["undone_at"]} for r in rows]


def undo(batch_id: str) -> dict:
    from app.services import memory_service

    with _conn() as conn:
        r = conn.execute("SELECT undo, undone_at FROM cleanup_log WHERE id = ?", (batch_id,)).fetchone()
    if not r:
        raise LookupError("No such cleanup.")
    if r["undone_at"]:
        raise ValueError("Already undone.")
    rag = _rag()
    restored = 0
    for step in reversed(json.loads(r["undo"])):
        if step["op"] == "delete_memory":
            memory_service.delete_memory(step["id"])
        elif step["op"] == "restore_memories":
            for m in step["rows"]:
                with _conn() as conn:
                    cols = ", ".join(m.keys())
                    conn.execute(f"INSERT OR REPLACE INTO memories ({cols}) VALUES ({', '.join('?' for _ in m)})",
                                 tuple(m.values()))
                rag.index_memory(m["id"], m["content"])
                restored += 1
        elif step["op"] == "enable_memory":
            memory_service.set_enabled(step["id"], True)
            restored += 1
        elif step["op"] == "restore_chunks":
            conn = rag._conn()  # noqa: SLF001
            conn.executemany("INSERT INTO chunks (source_kind, source_id, conversation_id, chunk_index, text, created_at)"
                             " VALUES (:source_kind, :source_id, :conversation_id, :chunk_index, :text, :created_at)", step["rows"])
            conn.commit()
            restored += len(step["rows"])
    try:
        rag._schedule_reindex()  # noqa: SLF001 — restored passages get their vectors back in the background
    except Exception as exc:  # noqa: BLE001
        log.debug("cleanup.reindex_schedule_failed", error=str(exc))
    with _conn() as conn:
        conn.execute("UPDATE cleanup_log SET undone_at = ? WHERE id = ?", (time.time(), batch_id))
    return {"restored": restored}
