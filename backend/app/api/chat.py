from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.logging import get_logger
from app.db import storage
from app.models.schemas import ChatRequest, ConversationCreate, ConversationRename
from app.services.ollama_client import OllamaClient, OllamaError
from app.services.orchestrator import build_turn_context, run_turn
from app.services.router import ModelRouter

log = get_logger(__name__)
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
    # Cascade: also remove any files bound to this conversation.
    try:
        from app.services.attachments import cleanup_for_conversation
        await asyncio.to_thread(cleanup_for_conversation, conversation_id)
    except Exception as exc:  # never let cleanup abort the delete
        log.warning("chat.delete_cleanup_failed", error=str(exc))
    storage.delete_conversation(conversation_id)
    return {"ok": True}


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    """
    Server-Sent Events stream. Each event is a JSON line of one of:
      {"type": "route", "model": ..., "role": ..., "reason": ...}
      {"type": "token", "text": ...}
      {"type": "downgrade", "from": ..., "to": ..., "reason": ...}
      {"type": "done"}
      {"type": "error", "message": ...}
    Plus an SSE comment frame `:heartbeat` is emitted every
    `sse_heartbeat_seconds` so reverse proxies with idle timeouts don't
    kill long-running streams.
    """
    # Sticky-routing signal: pull the last model used in *this* conversation
    # so the next turn can be served by the same model when nothing forces
    # a re-route. Falls back to the per-process last model (set below).
    history_last_model = None
    try:
        last_msgs = storage.get_messages(body.conversation_id)
        for m in reversed(last_msgs):
            if m.get("model"):
                history_last_model = m["model"]
                break
    except Exception:
        history_last_model = getattr(request.app.state, "last_route_model", None)

    try:
        decision, stream = await run_turn(
            body.conversation_id, body.message, body.attachment_ids,
            history_last_model=history_last_model,
        )
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    heartbeat = int(settings.get("sse_heartbeat_seconds", 15))

    async def event_gen():
        # Track which model is actually in flight so we can downgrade
        # to the configured fallback if it dies mid-stream.
        current_model = decision.model
        current_role = decision.role
        current_reason = decision.reason
        downgraded = False
        yield _sse({
            "type": "route",
            "model": current_model,
            "role": current_role,
            "reason": current_reason,
            "confidence": decision.confidence,
        })
        # Stash on app state so the next /api/route/preview call (and the
        # next /api/chat) can be sticky.
        try:
            request.app.state.last_route_model = current_model
        except Exception:
            pass

        last_emit = time.time()
        collected: list[str] = []
        try:
            async for piece in stream:
                collected.append(piece)
                yield _sse({"type": "token", "text": piece})
                # Heartbeat: emit a comment frame if the loop has been
                # quiet for a while, so the connection doesn't idle out.
                now = time.time()
                if heartbeat > 0 and (now - last_emit) > heartbeat:
                    yield ":heartbeat\n\n"
                    last_emit = now
        except OllamaError as exc:
            # Mid-stream failure on the chosen model — try the configured
            # fallback once before giving up (Tier 1 #5).
            if not downgraded:
                fallback = await _pick_fallback(request, current_model)
                if fallback and fallback != current_model:
                    downgraded = True
                    log.warning(
                        "chat.model_downgrade",
                        from_model=current_model,
                        to_model=fallback,
                        error=str(exc),
                    )
                    yield _sse({
                        "type": "downgrade",
                        "from": current_model,
                        "to": fallback,
                        "reason": f"Original model failed: {exc}",
                    })
                    try:
                        client = OllamaClient()
                        history = storage.get_messages(body.conversation_id)
                        # Rebuild messages from the just-saved user turn
                        # (the orchestrator already wrote the user message
                        # before kicking off the stream).
                        retry_stream = client.chat_stream(
                            fallback,
                            [m for m in history if m["role"] in {"user", "assistant"}][-int(settings.get("max_context_messages", 24)):],
                        )
                        last_emit = time.time()
                        async for piece in retry_stream:
                            collected.append(piece)
                            yield _sse({"type": "token", "text": piece})
                            now = time.time()
                            if heartbeat > 0 and (now - last_emit) > heartbeat:
                                yield ":heartbeat\n\n"
                                last_emit = now
                        # Promote the fallback as the "real" model for
                        # the persisted message.
                        current_model = fallback
                    except Exception as exc2:
                        log.error("chat.fallback_failed", error=str(exc2))
                        yield _sse({
                            "type": "error",
                            "message": f"Both {current_model} and fallback failed: {exc2}",
                        })
                        return
                else:
                    yield _sse({"type": "error", "message": str(exc)})
                    return
            else:
                yield _sse({"type": "error", "message": str(exc)})
                return

        # Don't persist a half-empty response on disconnect.
        full_text = "".join(collected)
        if not full_text.strip():
            yield _sse({"type": "error", "message": "Empty response (client likely disconnected)."})
            return

        storage.add_message(
            body.conversation_id, "assistant", full_text,
            model=current_model, route_role=current_role, route_reason=current_reason,
        )
        yield _sse({"type": "done"})

    return StreamingResponse(event_gen(), media_type="text/event-stream")


async def _pick_fallback(request: Request, current_model: str) -> str | None:
    """Resolve the fallback model from config, or `None` to skip the
    one-time retry. Resolution order: explicit `fallback_model` value
    (if it looks like a model name and is installed) > role-based
    resolution against the installed model set."""
    cfg = settings.get("fallback_model", "general")
    if not cfg:
        return None
    # If the user pinned a specific model name, use it directly.
    if cfg and not cfg.endswith("Model"):
        registry = getattr(request.app.state, "model_registry", None)
        # Lazy: construct a registry on the fly if the app didn't keep one.
        from app.services.router import ModelRegistry
        reg = registry or ModelRegistry()
        try:
            installed = await reg.models()
        except Exception:
            installed = []
        if cfg in installed and cfg != current_model:
            return cfg
    # Otherwise treat it as a role name.
    try:
        from app.services.router import ModelRegistry
        installed = await ModelRegistry().models()
        router_ = ModelRouter(registry=ModelRegistry())
        m = router_._match_capability(cfg, installed)  # noqa: SLF001
        if m and m != current_model:
            return m
    except Exception as exc:
        log.warning("chat.fallback_resolve_failed", error=str(exc))
    return None


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"