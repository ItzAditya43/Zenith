"""Memory management endpoints — backs the Settings → Memory panel.

  GET    /api/memories          — list all stored memories
  POST   /api/memories          — add one manually
  PATCH  /api/memories/{id}     — enable/disable one
  DELETE /api/memories/{id}     — forget one
  DELETE /api/memories          — forget everything
  POST   /api/memories/review-conflicts     — scan for contradictions now
  GET    /api/memories/conflicts            — list unresolved conflicts
  POST   /api/memories/conflicts/{id}/resolve — dismiss one
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.db import storage
from app.models.schemas import MemoryCreate, MemoryToggle
from app.services import memory_service

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memories")
async def list_memories():
    return memory_service.list_memories()


@router.post("/memories")
async def add_memory(body: MemoryCreate):
    row = memory_service.add_memory(body.content, body.category)
    if row is None:
        raise HTTPException(409, "Duplicate or invalid memory.")
    return row


@router.patch("/memories/{memory_id}")
async def toggle_memory(memory_id: str, body: MemoryToggle):
    memory_service.set_enabled(memory_id, body.enabled)
    return {"ok": True}


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
