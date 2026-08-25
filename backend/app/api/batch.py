"""Batch job endpoint: run one prompt template against every file in a
folder, streaming a result per file. See app/services/batch_service.py
for the actual per-file logic; this module is just the HTTP surface.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.logging import get_logger
from app.models.schemas import StrictModel
from app.services import batch_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/batch", tags=["batch"])


class BatchRunRequest(StrictModel):
    folder_path: str
    prompt_template: str
    model: str
    extensions: list[str] | None = None


def _sse(payload: dict[str, Any]) -> str:
    # Mirrors chat.py's `_sse` helper — same SSE framing convention used
    # everywhere else in this codebase for streamed responses.
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/run")
async def run_batch(body: BatchRunRequest):
    """Streams one SSE `data:` frame per file as it completes, then a
    final `done` frame. Each per-file frame is the dict batch_service
    yields, i.e. {"file", "status": "done"|"error", "result"|"error"}."""

    async def event_gen():
        try:
            async for item in batch_service.run_batch(
                body.folder_path, body.prompt_template, body.model, body.extensions
            ):
                yield _sse(item)
            yield _sse({"status": "done"})
        except Exception as exc:  # last-resort guard so the stream always terminates cleanly
            log.warning("batch.run_failed", error=str(exc))
            yield _sse({"status": "error", "error": str(exc)})

    return StreamingResponse(event_gen(), media_type="text/event-stream")
