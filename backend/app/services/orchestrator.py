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

import asyncio
from typing import AsyncIterator

from app.core.config import settings
from app.core.logging import get_logger
from app.db import storage
from app.services import attachments as att_service
from app.services import document_service, vision_service, whisper_service
from app.services.ollama_client import OllamaClient
from app.services.router import ModelRouter, RouteDecision

log = get_logger(__name__)


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
            ctx.has_long_document = len(raw) > settings.get("doc_chunk_chars", 6000)
            # Defer to multi-doc synthesizer below (handles 1+ documents
            # uniformly and labels each one for the model).
            ctx.text_parts.append(f"__DOC__:{att.filename}\n{raw}")
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

    # Split out document parts (marked with __DOC__:name) and feed them
    # through the multi-doc synthesizer so each is labeled and
    # proportionally budgeted. Other text parts (transcripts, OCR results)
    # join in as before.
    doc_parts: list[dict] = []
    other_parts: list[str] = []
    for p in ctx.text_parts:
        if p.startswith("__DOC__:"):
            name, _, body = p.partition("\n")
            doc_parts.append({"name": name[len("__DOC__:"):], "text": body})
        else:
            other_parts.append(p)

    sections: list[str] = []
    if doc_parts:
        sections.append(document_service.synthesize_multi_doc(doc_parts))
    if other_parts:
        sections.append("\n\n".join(other_parts))

    full_user_text = user_text
    if sections:
        full_user_text = (user_text + "\n\n" + "\n\n".join(sections)).strip()
    messages.append({"role": "user", "content": full_user_text})
    return messages


async def _build_system_context(conversation_id: str, user_text: str) -> str:
    """Compose the system message: user-configured persona/system prompt,
    long-term memories, and recall of relevant past-conversation excerpts.
    Any failing section is skipped."""
    parts: list[str] = []
    persona_prompt = None
    try:
        from app.services import persona_service
        persona_prompt = await asyncio.to_thread(
            persona_service.get_conversation_persona_prompt, conversation_id
        )
    except Exception as exc:
        log.debug("orchestrator.persona_lookup_failed", error=str(exc))
    # A conversation-level persona overrides the one global system prompt
    # rather than stacking with it — two standing instructions competing
    # for priority would be more confusing than useful.
    custom = persona_prompt or (settings.get("system_prompt") or "").strip()
    if custom:
        parts.append(custom)
    try:
        from app.db import storage
        from app.services import memory_service
        conv = await asyncio.to_thread(storage.get_conversation, conversation_id)
        project_id = conv.get("project_id") if conv else None
        block = await asyncio.to_thread(memory_service.memory_block, project_id)
        if block:
            parts.append(block)
    except Exception as exc:
        log.debug("orchestrator.memory_block_failed", error=str(exc))
    if bool(settings.get("recall_enabled", True)) and len(user_text.strip()) >= 12:
        try:
            from app.services import rag_service
            hits = await asyncio.to_thread(
                rag_service.retrieve,
                user_text,
                None,
                int(settings.get("recall_top_k", 3)),
                "message",
                conversation_id,
            )
            if hits:
                rendered = "\n".join(f"- {h['text'][:400]}" for h in hits)
                parts.append(
                    "Possibly relevant excerpts from your past conversations "
                    "with this user (ignore if not relevant):\n" + rendered
                )
        except Exception as exc:
            log.debug("orchestrator.recall_failed", error=str(exc))
    if bool(settings.get("folder_recall_enabled", True)) and len(user_text.strip()) >= 12:
        try:
            from app.services import rag_service
            hits = await asyncio.to_thread(
                rag_service.retrieve,
                user_text, None, int(settings.get("folder_recall_top_k", 3)), "folder",
            )
            if hits:
                rendered = "\n\n".join(
                    f"[{h['source_id']}]\n{h['text'][:600]}" for h in hits
                )
                parts.append(
                    "Possibly relevant content from your watched folders "
                    "(ignore if not relevant):\n" + rendered
                )
        except Exception as exc:
            log.debug("orchestrator.folder_recall_failed", error=str(exc))
    return "\n\n".join(parts)


async def _gather_web_context(user_text: str, web_search: bool) -> tuple[str, list[dict]]:
    """Fetches any URLs pasted in the message (always) plus, if
    `web_search` is on, the top DuckDuckGo results for the message text.
    Returns (context_section, sources) where `sources` is what the API
    layer emits as a `sources` SSE event for the UI to render as
    citations. Best-effort throughout — network failures degrade to "no
    web context" rather than failing the turn."""
    from app.services import web_service

    max_urls = int(settings.get("web_fetch_max_urls_per_turn", 3))
    urls = web_service.extract_urls(user_text, limit=max_urls) if max_urls > 0 else []

    search_results: list[dict] = []
    if web_search:
        try:
            search_results = await web_service.search(user_text)
        except Exception as exc:
            log.warning("orchestrator.web_search_failed", error=str(exc))

    # Fetch pasted URLs plus (if searching) the top search results not
    # already covered by a pasted URL, all concurrently.
    search_urls = [r["url"] for r in search_results if r["url"] not in urls]
    to_fetch = urls + search_urls
    if not to_fetch:
        return "", []

    pages = await asyncio.gather(
        *(web_service.fetch_url(u) for u in to_fetch), return_exceptions=True
    )

    sections: list[str] = []
    sources: list[dict] = []
    snippet_by_url = {r["url"]: r.get("snippet", "") for r in search_results}
    for url, page in zip(to_fetch, pages):
        if isinstance(page, Exception) or not page:
            # Fall back to the search snippet so a failed fetch doesn't
            # silently drop a result the user can see was found.
            if url in snippet_by_url and snippet_by_url[url]:
                sections.append(f"[{url}]\n{snippet_by_url[url]}")
                sources.append({"url": url, "title": url})
            continue
        sections.append(f"[{page['title']}]({page['url']})\n{page['text']}")
        sources.append({"url": page["url"], "title": page["title"]})

    if not sections:
        return "", []
    header = "Web content fetched for this turn (cite naturally, don't dump raw URLs):\n\n"
    return header + "\n\n---\n\n".join(sections), sources


async def run_turn(
    conversation_id: str,
    user_text: str,
    attachment_ids: list[str],
    history_last_model: str | None = None,
    web_search: bool = False,
    parent_message_id: str | None = None,
    parent_explicit: bool = False,
    regenerate_user_message_id: str | None = None,
) -> tuple[RouteDecision, AsyncIterator[str], list[dict], str]:
    """Returns the routing decision, an async generator of reply tokens,
    a list of web sources used (possibly empty), and the parent_id the
    caller should persist the assistant reply under.

    Branching (Settings has no toggle for this — it's implicit in how
    the API is called):
      - Normal send: `parent_explicit=False` -> auto-attaches under the
        conversation's current last active message.
      - Edit-and-resend: caller passes `parent_explicit=True` and the
        resolved `parent_message_id` (which is legitimately `None` when
        editing the very first message in a conversation — that's why
        this needs its own flag rather than treating `None` as "not
        specified"), and has already deactivated the old branch at that
        point — this just creates a new user message there.
      - Regenerate: caller passes `regenerate_user_message_id` instead
        of a fresh user message; the existing user turn is reused
        (no duplicate persisted) and only a new assistant sibling is
        created under it.
    """
    if regenerate_user_message_id:
        user_row = storage.get_message(regenerate_user_message_id)
        if not user_row:
            raise ValueError(f"No such message: {regenerate_user_message_id}")
        user_text = user_row["content"]
        attachment_ids = [a["id"] for a in user_row.get("attachments", [])]

    ctx = await build_turn_context(attachment_ids)
    history = storage.get_messages(conversation_id)
    messages = _build_messages(history, user_text, ctx)

    web_section, web_sources = await _gather_web_context(user_text, web_search)
    if web_section:
        messages[-1]["content"] = (messages[-1]["content"] + "\n\n" + web_section).strip()

    # Phase 5: if a document is attached, do a top-k retrieval against
    # the RAG index and use those chunks instead of head+tail truncation
    # so the model can answer questions about page 300, not just the
    # first and last pages. Falls back to the truncate path if no
    # embedding model is available.
    if ctx.attachment_summaries:
        try:
            from app.services import rag_service
            for att in ctx.attachment_summaries:
                if att.get("kind") != "document":
                    continue
                chunks = rag_service.retrieve(
                    user_text, source_id=att["id"],
                )
                if chunks:
                    rendered = "\n\n".join(
                        f"[From '{att['name']}']\n{c['text']}" for c in chunks
                    )
                    # Replace the raw doc text in messages[-1] with the
                    # retrieved, top-k chunk(s).
                    messages[-1]["content"] = (
                        user_text + "\n\n" + rendered
                    ).strip()
        except Exception as exc:
            log.warning("orchestrator.rag_failed", error=str(exc))

    # Personal-assistant context: system prompt + long-term memories +
    # recall of relevant excerpts from *other* conversations. All
    # best-effort — a failure here must never block the turn.
    system_text = await _build_system_context(conversation_id, user_text)
    if system_text:
        messages.insert(0, {"role": "system", "content": system_text})

    # Heuristic: pass a rough char count of the conversation (truncated
    # to max_context_messages worth) so the router can prefer a
    # larger-context model when needed.
    context_chars = sum(len(m["content"]) for m in messages)

    router = ModelRouter()
    decision = await router.decide(
        text=user_text,
        has_image=ctx.has_image,
        has_video=ctx.has_video,
        has_long_document=ctx.has_long_document,
        history_last_model=history_last_model,
        context_chars=context_chars,
    )

    if regenerate_user_message_id:
        # The user turn already exists — only a new assistant sibling is
        # being created under it. Re-indexing/re-persisting it would
        # duplicate history.
        assistant_parent_id = regenerate_user_message_id
    else:
        parent_for_user = (
            parent_message_id if parent_explicit
            else storage.get_last_active_message_id(conversation_id)
        )
        new_user_msg = storage.add_message(
            conversation_id, "user", user_text,
            attachments=ctx.attachment_summaries, parent_id=parent_for_user,
        )
        assistant_parent_id = new_user_msg["id"]
        try:
            from app.services import rag_service
            await asyncio.to_thread(rag_service.index_message, conversation_id, "user", user_text)
        except Exception as exc:
            log.debug("orchestrator.index_user_failed", error=str(exc))

    client = OllamaClient()
    stream = client.chat_stream(
        decision.model, messages, images_b64=ctx.images_b64 or None
    )
    return decision, stream, web_sources, assistant_parent_id