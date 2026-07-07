from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.db import storage
from app.models.schemas import ChatRequest, ConversationCreate, ConversationRename
from app.services.ollama_client import OllamaError
from app.services.orchestrator import run_turn

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/conversations")
async def list_conversations():
    return storage.list_conversations()


@router.post("/conversations")
async def create_conversation(body: ConversationCreate):
    return storage.create_conversation(body.title)


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: str):
    return storage.get_messages(conversation_id)


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, body: ConversationRename):
    storage.rename_conversation(conversation_id, body.title)
    return {"ok": True}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    storage.delete_conversation(conversation_id)
    return {"ok": True}


@router.post("/chat")
async def chat(body: ChatRequest):
    """
    Server-Sent Events stream. Each event is a JSON line of one of:
      {"type": "route", "model": ..., "role": ..., "reason": ...}
      {"type": "token", "text": ...}
      {"type": "done"}
      {"type": "error", "message": ...}
    """
    try:
        decision, stream = await run_turn(
            body.conversation_id, body.message, body.attachment_ids
        )
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    async def event_gen():
        yield _sse({
            "type": "route",
            "model": decision.model,
            "role": decision.role,
            "reason": decision.reason,
        })
        collected = []
        try:
            async for piece in stream:
                collected.append(piece)
                yield _sse({"type": "token", "text": piece})
        except OllamaError as exc:
            yield _sse({"type": "error", "message": str(exc)})
            return

        full_text = "".join(collected)
        storage.add_message(
            body.conversation_id, "assistant", full_text,
            model=decision.model, route_role=decision.role, route_reason=decision.reason,
        )
        yield _sse({"type": "done"})

    return StreamingResponse(event_gen(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
