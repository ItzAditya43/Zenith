from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile

from app.services import attachments as att_service

router = APIRouter(prefix="/api", tags=["upload"])

MAX_FILE_BYTES = 200 * 1024 * 1024  # 200MB, generous for local video clips


@router.post("/upload")
async def upload(file: UploadFile):
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "File too large (200MB limit).")

    att = att_service.save_upload(file.filename, data)
    return {
        "id": att.id,
        "filename": att.filename,
        "kind": att.kind,
        "size": len(data),
    }
