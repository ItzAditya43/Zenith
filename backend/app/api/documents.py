"""Document editing + download.

  POST /api/documents/{attachment_id}/edit      — apply an instruction, get an edited copy
  GET  /api/attachments/{attachment_id}/download — fetch an attachment's raw bytes
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from app.core.logging import get_logger
from app.models.schemas import StrictModel
from app.services import attachments as att_service
from app.services import document_service

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["documents"])


class DocumentEditRequest(StrictModel):
    instruction: str = Field(min_length=1, max_length=2000)


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: str):
    att = att_service.get(attachment_id)
    if not att or not att.path.exists():
        raise HTTPException(404, "No such attachment.")
    return FileResponse(att.path, filename=att.filename, media_type=att.mime_type)


@router.post("/documents/{attachment_id}/edit")
async def edit_document(attachment_id: str, body: DocumentEditRequest):
    att = att_service.get(attachment_id)
    if not att:
        raise HTTPException(404, "No such attachment.")
    ext = Path(att.filename).suffix.lower()
    if att.kind != "document" or ext not in document_service.EDITABLE_EXTS:
        raise HTTPException(
            400,
            f"Editing isn't supported for {ext or 'this'} files — only "
            f"{', '.join(sorted(document_service.EDITABLE_EXTS))} round-trip losslessly. "
            "PDF/DOCX formatting would be silently discarded.",
        )

    try:
        original_text = document_service.extract_text(att.path)
    except Exception as exc:
        raise HTTPException(500, f"Couldn't read the document: {exc}")

    from app.services.router import ModelRegistry, ModelRouter

    registry = ModelRegistry()
    installed = await registry.models()
    router_ = ModelRouter(registry=registry)
    model = router_._match_capability("general", installed)  # noqa: SLF001
    if not model and installed:
        model = installed[0]
    if not model:
        raise HTTPException(503, "No Ollama models installed.")

    try:
        edited_text = await document_service.edit_document(original_text, body.instruction, model)
    except Exception as exc:
        raise HTTPException(503, f"Edit failed: {exc}")
    if not edited_text.strip():
        raise HTTPException(502, "The model returned an empty document — original left untouched.")

    stem = Path(att.filename).stem
    new_filename = f"{stem}-edited{ext}"
    new_att = att_service.save_upload(
        new_filename, edited_text.encode("utf-8"),
        declared_mime=att.mime_type,
    )
    log.info("document.edited", source_id=attachment_id, new_id=new_att.id, model=model)
    return {
        "id": new_att.id,
        "filename": new_att.filename,
        "content": edited_text,
        "download_url": f"/api/attachments/{new_att.id}/download",
        "model": model,
    }
