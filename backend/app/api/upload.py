from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.services import attachments as att_service
from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["upload"])

MAX_FILE_BYTES = 200 * 1024 * 1024  # 200MB, generous for local video clips


@router.post("/upload")
async def upload(file: UploadFile, conversation_id: str | None = Form(None)):
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

    # Index documents into the RAG store in the background so "what's on
    # page 300" works via retrieval instead of head+tail truncation.
    if att.kind == "document":
        asyncio.create_task(_index_document(att, conversation_id))

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


@router.post("/import")
async def import_history(file: UploadFile):
    """Import a ChatGPT/Claude conversations.json, or a Zenith backup
    produced by GET /api/export/json, into this instance. Auto-detects
    which of the three it is from the JSON shape."""
    import json as _json
    from app.services import import_service

    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "File too large (200MB limit).")
    try:
        parsed_json = _json.loads(data.decode("utf-8", errors="ignore"))
    except _json.JSONDecodeError:
        raise HTTPException(400, "That file isn't valid JSON — upload the conversations.json from your export.")

    if import_service.is_zenith_backup(parsed_json):
        result = import_service.import_zenith_backup(parsed_json)
        log.info("import_completed", source="zenith", **result)
        return result

    try:
        normalized = import_service.detect_and_parse(parsed_json)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not normalized:
        raise HTTPException(400, "No importable conversations found in that file.")
    result = import_service.import_conversations(normalized)
    log.info("import_completed", source="chatgpt/claude", **result)
    return result


async def _index_document(att, conversation_id: str | None) -> None:
    """Best-effort background chunk+embed of an uploaded document."""
    try:
        from app.services import document_service, rag_service

        text = await asyncio.to_thread(document_service.extract_text, att.path)
        if text and text.strip():
            n = await asyncio.to_thread(
                rag_service.index_document, att.id, text, conversation_id
            )
            log.info("upload_indexed", attachment_id=att.id, chunks=n)
    except Exception as exc:
        log.warning("upload_index_failed", attachment_id=att.id, error=str(exc))
