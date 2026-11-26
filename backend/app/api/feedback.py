"""Answer feedback and saved model comparisons.

  PUT    /api/messages/{id}/feedback      — {rating: -1|0|1, wrong_model?, note?}
  DELETE /api/messages/{id}/feedback
  GET    /api/conversations/{id}/feedback — {message_id: feedback}
  GET    /api/feedback/summary            — per-model totals for routing diagnostics
  POST   /api/compare                     — run one prompt on 2–4 models (SSE)
  GET    /api/compare                     — saved comparisons
  GET    /api/compare/{id}
  POST   /api/compare/{id}/winner         — {model}
  DELETE /api/compare/{id}
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services import feedback_service as fb

router = APIRouter(prefix="/api", tags=["feedback"])


class FeedbackBody(BaseModel):
    rating: int | None = Field(default=None, ge=-1, le=1)
    wrong_model: bool | None = None
    note: str | None = Field(default=None, max_length=500)


class CompareBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    models: list[str] = Field(min_length=2, max_length=fb.MAX_MODELS)
    system: str | None = Field(default=None, max_length=4000)


class WinnerBody(BaseModel):
    model: str | None = Field(default=None, max_length=200)


@router.put("/messages/{message_id}/feedback")
async def put_feedback(message_id: str, body: FeedbackBody):
    try:
        return fb.set_feedback(message_id, body.rating, body.wrong_model, body.note)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/messages/{message_id}/feedback")
async def delete_feedback(message_id: str):
    fb.clear_feedback(message_id)
    return {"ok": True}


@router.get("/conversations/{conversation_id}/feedback")
async def conversation_feedback(conversation_id: str):
    return fb.feedback_for_conversation(conversation_id)


@router.get("/feedback/summary")
async def feedback_summary():
    return fb.summary()


@router.post("/compare")
async def compare(body: CompareBody):
    async def gen():
        async for ev in fb.run_compare(body.prompt, body.models, body.system):
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/compare")
async def list_compare():
    return fb.list_compares()


@router.get("/compare/{cid}")
async def get_compare(cid: str):
    run = fb.get_compare(cid)
    if not run:
        raise HTTPException(404, "No such comparison.")
    return run


@router.post("/compare/{cid}/winner")
async def winner(cid: str, body: WinnerBody):
    if not fb.set_winner(cid, body.model):
        raise HTTPException(400, "That model isn't part of this comparison.")
    return {"ok": True}


@router.delete("/compare/{cid}")
async def delete_compare(cid: str):
    fb.delete_compare(cid)
    return {"ok": True}
