from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, UploadFile

from app.services import attachments as att_service
from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["upload"])

MAX_FILE_BYTES = 200 * 1024 * 1024  # 200MB, generous for local video clips


@router.post("/upload")
async def upload(file: UploadFile, conversation_id: str | None = None):
    """Persist a multipart upload.

    `conversation_id` is optional; if the client knows the active
    conversation at upload time we persist the binding so the file
    survives backend restarts and is eligible for conversation-scoped
    cleanup on delete. If omitted, the upload is treated as a transient
    chip (still persisted to disk + DB, just unbound) and the orphan
    sweeper in `main.lifespan` reaps it after the configured TTL.
    """
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        log.warning("upload_too_large", filename=file.filename, size=len(data))
        raise HTTPException(413, "File too large (200MB limit).")

    try:
        att = att_service.save_upload(
            file.filename, data, conversation_id=conversation_id
        )
    except att_service.AttachmentError as exc:
        # 4xx: declared extension doesn't match sniffed content, etc.
        log.warning("upload_rejected", filename=file.filename, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))

    log.info(
        "upload_saved",
        attachment_id=att.id,
        filename=att.filename,
        kind=att.kind,
        size=len(data),
        conversation_id=conversation_id,
    )
    return {
        "id": att.id,
        "filename": att.filename,
        "kind": att.kind,
        "mime_type": att.mime_type,
        "size": len(data),
    }
