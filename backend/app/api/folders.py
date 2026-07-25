"""Watched folders — Settings -> Folders backs onto these.

  GET    /api/folders                — list
  POST   /api/folders                — add {path, extensions?}
  PATCH  /api/folders/{id}           — enable/disable
  DELETE /api/folders/{id}           — stop watching (also drops its chunks)
  POST   /api/folders/{id}/scan      — scan this folder now, return a summary
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.models.schemas import WatchedFolderCreate, WatchedFolderToggle
from app.services import folder_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/folders", tags=["folders"])


@router.get("")
async def list_folders():
    return folder_service.list_watched_folders()


@router.post("")
async def add_folder(body: WatchedFolderCreate):
    try:
        return folder_service.add_watched_folder(body.path, body.extensions)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/{folder_id}")
async def toggle_folder(folder_id: str, body: WatchedFolderToggle):
    if not folder_service.get_watched_folder(folder_id):
        raise HTTPException(404, "No such watched folder.")
    folder_service.set_folder_enabled(folder_id, body.enabled)
    return {"ok": True}


@router.delete("/{folder_id}")
async def remove_folder(folder_id: str):
    folder_service.remove_watched_folder(folder_id)
    return {"ok": True}


@router.post("/{folder_id}/scan")
async def scan_folder_now(folder_id: str):
    import asyncio

    folder = folder_service.get_watched_folder(folder_id)
    if not folder:
        raise HTTPException(404, "No such watched folder.")
    result = await asyncio.to_thread(folder_service.scan_folder, folder)
    return result
