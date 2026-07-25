"""Council of models: ask several local models the same question at
once and stream all their answers concurrently, instead of picking one
via the router. Free by construction — every model here is one you
already have installed in Ollama, running in parallel on hardware
that's otherwise sitting idle between turns.

Council answers are persisted as *siblings* under the same user message
(reusing the branching machinery from storage.py) — so after a council
run, the existing ‹ 1/3 › branch switcher on the assistant bubble lets
you flip between what each model said, and picking one to keep is just
switching to that branch.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from app.core.config import settings
from app.core.logging import get_logger
from app.services.ollama_client import OllamaClient, OllamaError
from app.services.orchestrator import (
    build_turn_context,
    _build_messages,  # noqa: SLF001 — shared context-assembly helper, same protocol as orchestrator.run_turn
    _build_system_context,  # noqa: SLF001
)

log = get_logger(__name__)

_SENTINEL = object()


async def run_council(
    conversation_id: str,
    user_text: str,
    attachment_ids: list[str],
    models: list[str],
) -> AsyncIterator[dict]:
    """Events: council_start (model list), council_token (per-model
    streamed piece), council_done (per-model final text + persisted
    message id), done (overall). Each model's failure is isolated — one
    bad/unavailable model doesn't take down the others."""
    from app.db import storage

    models = list(dict.fromkeys(m for m in models if m))[:6]  # dedupe, sane cap
    if not models:
        yield {"type": "error", "message": "No models selected for the council."}
        return

    ctx = await build_turn_context(attachment_ids)
    history = storage.get_messages(conversation_id)
    messages = _build_messages(history, user_text, ctx)
    system_text = await _build_system_context(conversation_id, user_text)
    if system_text:
        messages.insert(0, {"role": "system", "content": system_text})

    parent_for_user = storage.get_last_active_message_id(conversation_id)
    user_msg = storage.add_message(
        conversation_id, "user", user_text,
        attachments=ctx.attachment_summaries, parent_id=parent_for_user,
    )
    assistant_parent_id = user_msg["id"]

    yield {"type": "council_start", "models": models}

    queue: asyncio.Queue = asyncio.Queue()

    async def _run_one(model: str) -> None:
        collected: list[str] = []
        try:
            client = OllamaClient()
            async for piece in client.chat_stream(model, messages, images_b64=ctx.images_b64 or None):
                collected.append(piece)
                await queue.put({"type": "council_token", "model": model, "text": piece})
        except OllamaError as exc:
            await queue.put({"type": "council_error", "model": model, "message": str(exc)})
        except Exception as exc:
            log.warning("council.model_failed", model=model, error=str(exc))
            await queue.put({"type": "council_error", "model": model, "message": str(exc)})
        finally:
            full_text = "".join(collected)
            if full_text.strip():
                msg = storage.add_message(
                    conversation_id, "assistant", full_text,
                    model=model, route_role="council", route_reason="Council of models",
                    parent_id=assistant_parent_id,
                )
                await queue.put({"type": "council_done", "model": model, "text": full_text, "message_id": msg["id"]})
            else:
                await queue.put({"type": "council_done", "model": model, "text": "", "message_id": None})
            await queue.put(_SENTINEL)

    tasks = [asyncio.create_task(_run_one(m)) for m in models]
    finished = 0
    first_persisted_id: str | None = None
    while finished < len(models):
        item = await queue.get()
        if item is _SENTINEL:
            finished += 1
            continue
        if item["type"] == "council_done" and item.get("message_id") and first_persisted_id is None:
            first_persisted_id = item["message_id"]
        yield item

    await asyncio.gather(*tasks, return_exceptions=True)

    # Exactly one sibling should end up active; default to the first
    # model in the list that actually produced a persisted answer.
    if first_persisted_id:
        storage.set_active_branch(conversation_id, first_persisted_id)

    # Index the user turn for cross-conversation recall (assistant
    # replies are per-model and each gets indexed by the API layer).
    try:
        from app.services import rag_service
        await asyncio.to_thread(rag_service.index_message, conversation_id, "user", user_text)
    except Exception as exc:
        log.debug("council.index_user_failed", error=str(exc))

    yield {"type": "done", "parent_id": assistant_parent_id}
