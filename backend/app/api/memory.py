"""Memory management endpoints — backs the Settings → Memory panel.

  GET    /api/memories          — list all stored memories
  POST   /api/memories          — add one manually
  PATCH  /api/memories/{id}     — enable/disable one
  DELETE /api/memories/{id}     — forget one
  DELETE /api/memories          — forget everything
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
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
