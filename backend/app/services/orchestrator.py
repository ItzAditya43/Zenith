"""Ties everything together for one chat turn:

  attachments -> (transcribe / extract text / sample frames)
              -> build message + image list
              -> ModelRouter picks a model
              -> OllamaClient streams the reply
              -> persisted to SQLite

This is the one place that "knows" how all the modalities become a single
list of chat messages, so routes stay thin.
"""
from __future__ import annotations

from typing import AsyncIterator

from app.core.config import settings
from app.db import storage
from app.services import attachments as att_service
from app.services import document_service, vision_service, whisper_service
from app.services.ollama_client import OllamaClient
from app.services.router import ModelRouter, RouteDecision


class TurnContext:
    """Everything gathered from attachments for a single user turn."""

    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.images_b64: list[str] = []
        self.has_image = False
        self.has_video = False
        self.has_long_document = False
        self.attachment_summaries: list[dict] = []


async def build_turn_context(attachment_ids: list[str]) -> TurnContext:
    ctx = TurnContext()
    for aid in attachment_ids:
        att = att_service.get(aid)
        if not att:
            continue

        if att.kind == "image":
            ctx.images_b64.append(vision_service.encode_image(att.path))
            ctx.has_image = True
            ctx.attachment_summaries.append({"id": aid, "kind": "image", "name": att.filename})

        elif att.kind == "video":
            ctx.has_video = True
            frames = vision_service.sample_frames(att.path)
            ctx.images_b64.extend(frames)
            try:
                audio_path = vision_service.extract_audio(att.path)
                transcript = whisper_service.transcribe(audio_path)
                if transcript["text"]:
                    ctx.text_parts.append(
                        f"[Transcript of video '{att.filename}']\n{transcript['text']}"
                    )
            except Exception as exc:  # ffmpeg missing, no audio track, etc.
                ctx.text_parts.append(f"[Could not extract audio from video: {exc}]")
            ctx.attachment_summaries.append(
                {"id": aid, "kind": "video", "name": att.filename, "frames": len(frames)}
            )

        elif att.kind == "document":
            raw = document_service.extract_text(att.path)
            chunked = document_service.chunk_for_context(raw)
            ctx.has_long_document = len(raw) > settings.get("doc_chunk_chars", 6000)
            ctx.text_parts.append(f"[Contents of document '{att.filename}']\n{chunked}")
            ctx.attachment_summaries.append({"id": aid, "kind": "document", "name": att.filename})

        elif att.kind == "audio":
            transcript = whisper_service.transcribe(att.path)
            ctx.text_parts.append(f"[Transcript of voice message]\n{transcript['text']}")
            ctx.attachment_summaries.append({"id": aid, "kind": "audio", "name": att.filename})

    return ctx


def _build_messages(history: list[dict], user_text: str, ctx: TurnContext) -> list[dict]:
    max_msgs = settings.get("max_context_messages", 24)
    trimmed = history[-max_msgs:]
    messages = [{"role": m["role"], "content": m["content"]} for m in trimmed]

    full_user_text = user_text
    if ctx.text_parts:
        full_user_text = (user_text + "\n\n" + "\n\n".join(ctx.text_parts)).strip()
    messages.append({"role": "user", "content": full_user_text})
    return messages


async def run_turn(
    conversation_id: str,
    user_text: str,
    attachment_ids: list[str],
) -> tuple[RouteDecision, AsyncIterator[str]]:
    """Returns the routing decision plus an async generator of reply tokens.
    The caller (API route) is responsible for streaming tokens to the client
    and persisting the final assembled text."""
    ctx = await build_turn_context(attachment_ids)
    history = storage.get_messages(conversation_id)
    messages = _build_messages(history, user_text, ctx)

    router = ModelRouter()
    decision = await router.decide(
        text=user_text,
        has_image=ctx.has_image,
        has_video=ctx.has_video,
        has_long_document=ctx.has_long_document,
    )

    storage.add_message(
        conversation_id, "user", user_text, attachments=ctx.attachment_summaries
    )

    client = OllamaClient()
    stream = client.chat_stream(
        decision.model, messages, images_b64=ctx.images_b64 or None
    )
    return decision, stream
