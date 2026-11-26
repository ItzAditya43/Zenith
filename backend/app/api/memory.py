"""Memory management endpoints — backs the Settings → Memory panel.

  GET    /api/memories          — list all stored memories
  POST   /api/memories          — add one manually
  GET    /api/memories/browse   — search + filter (q, scope, status) with provenance
  GET    /api/memories/export   — everything, as JSON
  PATCH  /api/memories/{id}     — edit text, scope, enabled, or approve (status)
  POST   /api/memories/merge    — replace several with one
  DELETE /api/memories/{id}     — forget one
  DELETE /api/memories          — forget everything
  POST   /api/memories/review-conflicts     — scan for contradictions now
  GET    /api/memories/conflicts            — list unresolved conflicts
  POST   /api/memories/conflicts/{id}/resolve — dismiss one
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.db import storage
from app.models.schemas import MemoryCreate, MemoryMerge, MemoryUpdate
from app.services import memory_service

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memories")
async def list_memories(since: float | None = None):
    """`since` (unix seconds) limits the list to memories created after it —
    the chat UI uses it to announce what a reply just taught Zenith."""
    rows = memory_service.list_memories()
    if since is not None:
        rows = [r for r in rows if (r.get("created_at") or 0) > since]
    return rows



@router.post("/memories")
async def add_memory(body: MemoryCreate):
    row = memory_service.add_memory(body.content, body.category)
    if row is None:
        raise HTTPException(409, "Duplicate or invalid memory.")
    return row


@router.get("/memories/browse")
async def browse_memories(q: str = "", scope: str | None = None, status: str | None = None,
                          project_id: str | None = None, conversation_id: str | None = None):
    return memory_service.search_memories(q, scope, status, project_id, conversation_id)


@router.get("/memories/export")
async def export_memories():
    return JSONResponse(
        memory_service.export_memories(),
        headers={"Content-Disposition": 'attachment; filename="zenith-memories.json"'},
    )


@router.post("/memories/merge")
async def merge_memories(body: MemoryMerge):
    try:
        return memory_service.merge_memories(body.ids, body.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/memories/{memory_id}")
async def update_memory(memory_id: str, body: MemoryUpdate):
    try:
        row = memory_service.update_memory(
            memory_id, content=body.content, enabled=body.enabled, scope=body.scope,
            conversation_id=body.conversation_id, project_id=body.project_id, status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "No such memory.")
    return row


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str):
    memory_service.delete_memory(memory_id)
    return {"ok": True}


@router.delete("/memories")
async def clear_memories():
    removed = memory_service.clear_memories()
    log.info("memory.cleared", removed=removed)
    return {"ok": True, "removed": removed}


@router.post("/memories/review-conflicts")
async def review_memory_conflicts():
    """Explicit, on-demand scan — see memory_service.review_conflicts for
    why this isn't automatic on every save."""
    created = await memory_service.review_conflicts()
    return {"found": len(created), "conflicts": created}


@router.get("/memories/conflicts")
async def list_memory_conflicts():
    conflicts = storage.list_memory_conflicts()
    by_id = {m["id"]: m for m in memory_service.list_memories()}
    enriched = []
    for c in conflicts:
        mem_a = by_id.get(c["memory_id_a"])
        mem_b = by_id.get(c["memory_id_b"])
        if not mem_a or not mem_b:
            # One side was deleted/disabled between the scan and now —
            # not actionable, silently drop it rather than show a
            # broken row.
            storage.resolve_memory_conflict(c["id"])
            continue
        enriched.append({**c, "memory_a": mem_a, "memory_b": mem_b})
    return enriched


@router.post("/memories/conflicts/{conflict_id}/resolve")
async def resolve_memory_conflict(conflict_id: str):
    storage.resolve_memory_conflict(conflict_id)
    return {"ok": True}


# ---- knowledge cleanup -----------------------------------------------------------

@router.get("/cleanup/scan")
async def cleanup_scan():
    """Proposed fixes for duplicate, stale and orphaned memories and index entries."""
    import asyncio

    from app.services import cleanup_service

    return {"proposals": await asyncio.to_thread(cleanup_service.scan), "history": cleanup_service.history()}


@router.post("/cleanup/apply")
async def cleanup_apply(body: dict):
    import asyncio

    from app.services import cleanup_service

    ids = [str(x) for x in (body.get("ids") or [])][:500]
    return await asyncio.to_thread(cleanup_service.apply, ids)


@router.post("/cleanup/undo/{batch_id}")
async def cleanup_undo(batch_id: str):
    import asyncio

    from app.services import cleanup_service

    try:
        return await asyncio.to_thread(cleanup_service.undo, batch_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

