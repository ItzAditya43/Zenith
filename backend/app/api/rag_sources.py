"""Visibility + cleanup for the RAG index.

RAG (documents, watched folders, cross-conversation message recall,
memories) is otherwise invisible infrastructure — nothing shows the user
what's actually contributing to retrieval across the whole install, or
lets them remove one source. This is a thin read/delete layer over
rag_service's chunk store; it doesn't touch retrieval logic itself.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.logging import get_logger
from app.services import rag_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.get("/sources")
async def list_sources():
    import asyncio
    sources = await asyncio.to_thread(rag_service.list_sources)
    return {"sources": sources}


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: str,
    source_kind: str = Query(..., description="Kind of the source to delete (e.g. document, folder, message, memory)."),
):
    import asyncio
    deleted = await asyncio.to_thread(rag_service.delete_source, source_id, source_kind)
    if deleted == 0:
        raise HTTPException(404, "No chunks found for that source_id/source_kind.")
    log.info("rag_sources.deleted", source_id=source_id, source_kind=source_kind, chunks=deleted)
    return {"deleted": deleted}
