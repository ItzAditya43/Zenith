"""Settings change history — see settings_history_service.py.

  GET  /api/settings/history              — recent changes (optional ?key=&limit=)
  POST /api/settings/history/{id}/revert  — revert one setting back to its old value
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services import settings_history_service

router = APIRouter(prefix="/api/settings/history", tags=["settings_history"])


@router.get("")
async def get_history(key: str | None = None, limit: int = 100):
    return settings_history_service.list_history(key=key, limit=limit)


@router.post("/{history_id}/revert")
async def revert(history_id: str):
    try:
        return settings_history_service.revert_to(history_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
