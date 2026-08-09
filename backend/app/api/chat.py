from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.logging import get_logger
from app.core.rate_limit import conversation_lock
from app.db import storage
from app.models.schemas import (
    ChatRequest,
    ConversationCreate,
    ConversationPersonaSet,
    ConversationRename,
    ConversationWorkdirSet,
    CouncilRequest,
    PersonaCreate,
    PersonaUpdate,
)
from app.services.ollama_client import OllamaClient, OllamaError
from app.services.orchestrator import build_turn_context, run_turn
from app.services.router import ModelRouter
from app.services.stream_registry import registry

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/conversations")
async def list_conversations():
    return storage.list_conversations()


@router.get("/conversations/search")
async def search_conversations(q: str = ""):
    """Full-text search across message content using SQLite FTS5. Used by
    the sidebar search bar (Phase 6 #5). Falls back to a LIKE scan if
    FTS5 isn't compiled in."""
    return storage.search_conversations(q)


@router.get("/search/all")
async def search_all(q: str = ""):
    """Unified search across conversations, documents, and memories in one
    call — powers the grouped sidebar search results."""
    return storage.search_all(q)


@router.post("/conversations")
async def create_conversation(body: ConversationCreate):
    return storage.create_conversation(body.title, body.project_id)


@router.patch("/conversations/{conversation_id}/project")
async def set_conversation_project(conversation_id: str, body: dict):
    storage.set_conversation_project(conversation_id, body.get("project_id"))
    return {"ok": True}


@router.get("/projects")
async def list_projects():
    return storage.list_projects()


@router.post("/projects")
async def create_project(body: dict):
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(422, "name is required.")
    return storage.create_project(name, body.get("workdir"))


@router.delete("/projects/{project_id}")
async def remove_project(project_id: str):
    storage.delete_project(project_id)
    return {"ok": True}


@router.patch("/projects/{project_id}/agent-mode")
async def set_project_agent_mode(project_id: str, body: dict):
    """Per-project autonomy override for agent mode — None/omitted falls
    back to the global `agent_mode` setting (see agent_service.py)."""
    mode = body.get("agent_mode")
    if mode is not None and mode not in ("manual", "semi", "full", "plan"):
        raise HTTPException(422, "agent_mode must be one of manual/semi/full/plan, or null.")
    storage.set_project_agent_mode(project_id, mode)
    return {"ok": True}


@router.patch("/conversations/{conversation_id}/pin")
async def set_conversation_pinned(conversation_id: str, body: dict):
    storage.set_conversation_pinned(conversation_id, bool(body.get("pinned")))
    return {"ok": True}


@router.patch("/conversations/{conversation_id}/tags")
async def set_conversation_tags(conversation_id: str, body: dict):
    tags = body.get("tags")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise HTTPException(422, "tags must be a list of strings.")
    storage.set_conversation_tags(conversation_id, tags[:20])
    return {"ok": True}


@router.post("/conversations/{conversation_id}/share")
async def share_conversation(conversation_id: str):
    if not storage.get_conversation(conversation_id):
        raise HTTPException(404, "No such conversation.")
    token = storage.create_share_link(conversation_id)
    return {"token": token}


@router.delete("/conversations/{conversation_id}/share")
async def unshare_conversation(conversation_id: str):
    storage.revoke_share_link(conversation_id)
    return {"ok": True}


@router.get("/share/{token}")
async def view_shared_conversation(token: str):
    """Public, read-only — deliberately not behind the passcode-lock
    middleware (see main.py's lock allowlist) so a link works for anyone
    it's sent to, the same trust model as "anyone with the link can view"
    sharing elsewhere. Returns just enough to render: title + messages,
    no working directory, tags, or other owner-only metadata."""
    conv = storage.get_conversation_by_share_token(token)
    if not conv:
        raise HTTPException(404, "This link is invalid or has been revoked.")
    messages = storage.get_messages(conv["id"])
    return {
        "title": conv["title"],
        "created_at": conv["created_at"],
        "messages": [
            {"role": m["role"], "content": m["content"], "model": m.get("model"), "created_at": m["created_at"]}
            for m in messages
        ],
    }


@router.get("/snippets")
async def list_snippets():
    return storage.list_snippets()


@router.post("/snippets")
async def create_snippet(body: dict):
    title = str(body.get("title", "")).strip()
    content = str(body.get("content", "")).strip()
    if not title or not content:
        raise HTTPException(422, "title and content are required.")
    return storage.create_snippet(title[:200], content[:20_000])


@router.delete("/snippets/{snippet_id}")
async def remove_snippet(snippet_id: str):
    storage.delete_snippet(snippet_id)
    return {"ok": True}


@router.get("/quick-actions")
async def list_quick_actions():
    return storage.list_quick_actions()


@router.post("/quick-actions")
async def create_quick_action(body: dict):
    name = str(body.get("name", "")).strip()
    prompt_template = str(body.get("prompt_template", "")).strip()
    if not name or not prompt_template:
        raise HTTPException(422, "name and prompt_template are required.")
    return storage.create_quick_action(name[:100], prompt_template[:5000], bool(body.get("auto_send")))


@router.delete("/quick-actions/{quick_action_id}")
async def remove_quick_action(quick_action_id: str):
    storage.delete_quick_action(quick_action_id)
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: str):
    return storage.get_messages(conversation_id)


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, body: ConversationRename):
    storage.rename_conversation(conversation_id, body.title)
    return {"ok": True}


@router.post("/conversations/{conversation_id}/title")
async def generate_title(conversation_id: str, body: ConversationRename):
    """Generate a short title from seed text (the first user message) and
    persist it. Returns {"title": null} when generation fails — the client
    treats the title as best-effort."""
    from app.services.title_service import generate_title as _gen
    title = await _gen(body.title)
    if title:
        storage.rename_conversation(conversation_id, title)
    return {"title": title}


@router.get("/conversations/{conversation_id}/branches")
async def list_branches(conversation_id: str):
    """Points in the tree with more than one version, keyed by parent_id
    ("root" for the very first message). The UI uses this to know where
    to render a "‹ 2/3 ›" switcher — most conversations have none."""
    return storage.list_branch_points(conversation_id)


@router.post("/conversations/{conversation_id}/messages/{message_id}/activate")
async def activate_branch(conversation_id: str, message_id: str):
    storage.set_active_branch(conversation_id, message_id)
    return {"ok": True, "messages": storage.get_messages(conversation_id)}


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
async def delete_message(conversation_id: str, message_id: str):
    """Delete a message and its whole downstream subtree; returns the
    refreshed active message list."""
    deleted = storage.delete_message(conversation_id, message_id)
    return {"ok": True, "deleted": deleted, "messages": storage.get_messages(conversation_id)}


@router.patch("/conversations/{conversation_id}/persona")
async def set_conversation_persona(conversation_id: str, body: ConversationPersonaSet):
    from app.services import persona_service
    if body.persona_id and not persona_service.get_persona(body.persona_id):
        raise HTTPException(404, "No such persona.")
    persona_service.set_conversation_persona(conversation_id, body.persona_id)
    return {"ok": True}


@router.get("/personas")
async def list_personas():
    from app.services import persona_service
    return persona_service.list_personas()


@router.patch("/conversations/{conversation_id}/workdir")
async def set_conversation_workdir(conversation_id: str, body: ConversationWorkdirSet):
    """Binds this conversation to a project directory — agent mode's
    bash cwd and relative file paths resolve against it, so you don't
    repeat the full path every message. Validated the same way a
    watched folder is (must exist, must be a directory, on whatever
    filesystem the backend process can see)."""
    from pathlib import Path

    if body.workdir:
        p = Path(body.workdir).expanduser()
        if not p.exists() or not p.is_dir():
            raise HTTPException(
                400, f"Not a directory (or not visible to the backend process): {body.workdir}"
            )
        resolved = str(p.resolve())
    else:
        resolved = None
    storage.set_conversation_workdir(conversation_id, resolved)
    return {"ok": True, "workdir": resolved}


@router.post("/personas")
async def create_persona(body: PersonaCreate):
    from app.services import persona_service
    return persona_service.create_persona(body.name, body.system_prompt, body.icon)


@router.patch("/personas/{persona_id}")
async def update_persona(persona_id: str, body: PersonaUpdate):
    from app.services import persona_service
    if not persona_service.get_persona(persona_id):
        raise HTTPException(404, "No such persona.")
    persona_service.update_persona(persona_id, body.name, body.system_prompt, body.icon)
    return {"ok": True}


@router.delete("/personas/{persona_id}")
async def delete_persona(persona_id: str):
    from app.services import persona_service
    persona_service.delete_persona(persona_id)
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
      {"type": "sources", "sources": [{"url":..., "title":...}, ...]}
      {"type": "tool_call"/"tool_pending"/"tool_result"/"tool_denied", ...}  (agent/research modes)
      {"type": "memory_saved", "facts": ["...", ...]}  (only when something new was remembered)
      {"type": "token", "text": ...}
      {"type": "downgrade", "from": ..., "to": ..., "reason": ...}
      {"type": "done"}
      {"type": "error", "message": ...}
    Plus an SSE comment frame `:heartbeat` is emitted every
    `sse_heartbeat_seconds` so reverse proxies with idle timeouts don't
    kill long-running streams.

    A per-conversation lock (Tier 7 #2) serializes turns so spamming send
    can't fan out into N concurrent Ollama streams and OOM the host.

    When `agent_mode_on` is set and agent tool use is enabled server-side,
    the turn is instead driven by `agent_service.run_agent_turn` — a
    multi-step tool loop (bash/files/web) — and the stream additionally
    carries `tool_call` / `tool_pending` / `tool_result` / `tool_denied`
    events. See `_agent_event_gen` below.
    """
    if body.agent_mode_on and bool(settings.get("agent_enabled", False)):
        async def agent_guarded_gen():
            try:
                async with conversation_lock(body.conversation_id):
                    async for ev in _agent_event_gen(body, request):
                        yield ev
            except TimeoutError as exc:
                yield _sse({"type": "error", "message": str(exc)})

        return StreamingResponse(agent_guarded_gen(), media_type="text/event-stream")

    if body.deep_research:
        async def research_guarded_gen():
            try:
                async with conversation_lock(body.conversation_id):
                    async for ev in _research_event_gen(body, request):
                        yield ev
            except TimeoutError as exc:
                yield _sse({"type": "error", "message": str(exc)})

        return StreamingResponse(research_guarded_gen(), media_type="text/event-stream")

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

    # Branching: an explicit edit-and-resend hides whatever was
    # previously below the edited message's parent (the old edited
    # message and anything after it) before the new user message gets
    # created there. Resolved server-side from the edited message's own
    # id — its parent may legitimately be None (editing the very first
    # message), which is why the client sends *which message* rather
    # than a parent that can't distinguish "root" from "not specified".
    parent_message_id: str | None = None
    parent_explicit = False
    if body.edit_of:
        edit_msg = storage.get_message(body.edit_of)
        if not edit_msg:
            raise HTTPException(404, "No such message to edit.")
        parent_message_id = edit_msg.get("parent_id")
        parent_explicit = True
        if parent_message_id is None:
            storage.deactivate_root(body.conversation_id)
        else:
            storage.deactivate_subtree(parent_message_id)
    # Branching: a regenerate hides the old assistant sibling(s) under
    # the user message it's replying to before generating a fresh one.
    if body.regenerate_of:
        regen_msg = storage.get_message(body.regenerate_of)
        if not regen_msg or not regen_msg.get("parent_id"):
            raise HTTPException(404, "No such message to regenerate.")
        storage.deactivate_subtree(regen_msg["parent_id"])

    try:
        decision, stream, web_sources, assistant_parent_id = await run_turn(
            body.conversation_id, body.message, body.attachment_ids,
            history_last_model=history_last_model,
            web_search=body.web_search,
            parent_message_id=parent_message_id,
            parent_explicit=parent_explicit,
            regenerate_user_message_id=body.regenerate_of,
            model_override=body.model_override,
        )
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    heartbeat = int(settings.get("sse_heartbeat_seconds", 15))

    async def produce():
        """Runs independently of the request that started it — see
        stream_registry.py. A dropped connection no longer kills
        generation or loses the reply; a `/resume` reconnect just
        re-subscribes to the same run."""
        key = body.conversation_id
        current_model = decision.model
        current_role = decision.role
        current_reason = decision.reason
        downgraded = False
        collected: list[str] = []
        turn_start = time.monotonic()
        first_token_ms: int | None = None
        try:
            async with conversation_lock(key):
                try:
                    async for piece in _with_heartbeat(stream, heartbeat):
                        if piece is None:
                            continue  # heartbeats aren't replayed — a resumer doesn't need them
                        if first_token_ms is None:
                            first_token_ms = int((time.monotonic() - turn_start) * 1000)
                        collected.append(piece)
                        await registry.publish(key, _sse({"type": "token", "text": piece}))
                except OllamaError as exc:
                    if not downgraded:
                        fallback = await _pick_fallback(request, current_model)
                        if fallback and fallback != current_model:
                            downgraded = True
                            log.warning("chat.model_downgrade", from_model=current_model, to_model=fallback, error=str(exc))
                            await registry.publish(key, _sse({
                                "type": "downgrade", "from": current_model, "to": fallback,
                                "reason": f"Original model failed: {exc}",
                            }))
                            try:
                                client = OllamaClient()
                                history = storage.get_messages(key)
                                retry_stream = client.chat_stream(
                                    fallback,
                                    [m for m in history if m["role"] in {"user", "assistant"}][-int(settings.get("max_context_messages", 24)):],
                                )
                                async for piece in _with_heartbeat(retry_stream, heartbeat):
                                    if piece is None:
                                        continue
                                    collected.append(piece)
                                    await registry.publish(key, _sse({"type": "token", "text": piece}))
                                current_model = fallback
                            except Exception as exc2:
                                log.error("chat.fallback_failed", error=str(exc2))
                                await registry.publish(key, _sse({
                                    "type": "error", "message": f"Both {current_model} and fallback failed: {exc2}",
                                }))
                                return
                        else:
                            await registry.publish(key, _sse({"type": "error", "message": str(exc)}))
                            return
                    else:
                        await registry.publish(key, _sse({"type": "error", "message": str(exc)}))
                        return

                full_text = "".join(collected)
                if not full_text.strip():
                    await registry.publish(key, _sse({"type": "error", "message": "Empty response from the model."}))
                    return

                storage.add_message(
                    key, "assistant", full_text,
                    model=current_model, route_role=current_role, route_reason=current_reason,
                    parent_id=assistant_parent_id,
                )
                try:
                    from app.services import rag_service
                    await asyncio.to_thread(rag_service.index_message, key, "assistant", full_text)
                except Exception as exc:
                    log.warning("chat.rag_index_failed", error=str(exc))

                try:
                    from app.services import memory_service
                    added = await memory_service.extract_from_text(body.message, key)
                    if added:
                        await registry.publish(key, _sse({
                            "type": "memory_saved", "facts": [m["content"] for m in added],
                        }))
                except Exception as exc:
                    log.debug("chat.memory_extract_failed", error=str(exc))

                if not getattr(request.app.state, "_titled_for", None):
                    request.app.state._titled_for = set()
                if key not in request.app.state._titled_for:
                    request.app.state._titled_for.add(key)
                    try:
                        from app.services.title_service import maybe_generate_title
                        maybe_generate_title(key, full_text)
                    except Exception as exc:
                        log.debug("chat.title_gen_failed", error=str(exc))

                try:
                    storage.record_usage_event(
                        current_model, current_role, len(collected),
                        int((time.monotonic() - turn_start) * 1000), first_token_ms,
                    )
                except Exception as exc:
                    log.debug("chat.usage_record_failed", error=str(exc))

                await registry.publish(key, _sse({"type": "done"}))
        except TimeoutError as exc:
            await registry.publish(key, _sse({"type": "error", "message": str(exc)}))
        except Exception as exc:
            log.error("chat.produce_failed", error=str(exc))
            await registry.publish(key, _sse({"type": "error", "message": str(exc)}))
        finally:
            await registry.finish(key)
            registry.cleanup_later(key)

    async def event_gen():
        yield _sse({
            "type": "route", "model": decision.model, "role": decision.role,
            "reason": decision.reason, "confidence": decision.confidence,
        })
        if web_sources:
            yield _sse({"type": "sources", "sources": web_sources})
        try:
            request.app.state.last_route_model = decision.model
        except Exception:
            pass

        key = body.conversation_id
        registry.start(key)
        asyncio.create_task(produce())
        q = await registry.subscribe(key)
        while True:
            frame = await q.get()
            if frame is None:
                break
            yield frame

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/conversations/{conversation_id}/chat/resume")
async def resume_chat(conversation_id: str):
    """Reconnects to an in-flight (or just-finished) generation for this
    conversation after a dropped SSE connection — replays whatever was
    already buffered, then continues live. 404 if there's nothing to
    resume (never started, or the run aged out — see stream_registry.py),
    which tells the client to give up and treat the reply as lost rather
    than retry forever."""
    q = await registry.subscribe(conversation_id)
    if q is None:
        raise HTTPException(404, "Nothing to resume for this conversation.")

    async def gen():
        while True:
            frame = await q.get()
            if frame is None:
                break
            yield frame

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/council")
async def council(body: CouncilRequest):
    """Server-Sent Events stream, one turn fanned out to several models
    concurrently instead of routed to one. Each event is one of:
      {"type": "council_start", "models": [...]}
      {"type": "council_token", "model": ..., "text": ...}
      {"type": "council_error", "model": ..., "message": ...}
      {"type": "council_done", "model": ..., "text": ..., "message_id": ...}
      {"type": "done"}
      {"type": "error", "message": ...}

    Results persist as branch siblings under the same user message (see
    council_service.py) — the chat UI's existing branch switcher is how
    you pick which model's answer to keep."""
    from app.services import council_service

    async def council_guarded_gen():
        try:
            async with conversation_lock(body.conversation_id):
                async for ev in council_service.run_council(
                    body.conversation_id, body.message, body.attachment_ids, body.models,
                ):
                    yield _sse(ev)
        except TimeoutError as exc:
            yield _sse({"type": "error", "message": str(exc)})
        except Exception as exc:
            log.error("council.failed", error=str(exc))
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(council_guarded_gen(), media_type="text/event-stream")


async def _agent_event_gen(body: ChatRequest, request: Request) -> AsyncIterator[str]:
    """Drives an agent-mode turn: consumes agent_service.run_agent_turn's
    structured events, forwards them as SSE, and — on `done` — persists
    the final assistant message and runs the same post-turn housekeeping
    (RAG indexing, memory extraction, auto-title) as the normal path."""
    from app.services import agent_service

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
        async for ev in agent_service.run_agent_turn(
            body.conversation_id, body.message, body.attachment_ids,
            history_last_model=history_last_model,
            model_override=body.model_override,
        ):
            etype = ev.get("type")
            if etype == "done":
                full_text = ev["full_text"]
                if not full_text.strip():
                    yield _sse({"type": "error", "message": "Empty response."})
                    return
                storage.add_message(
                    body.conversation_id, "assistant", full_text,
                    model=ev.get("model"), route_role=ev.get("role"), route_reason=ev.get("reason"),
                    parent_id=ev.get("parent_id"),
                )
                try:
                    from app.services import rag_service
                    await asyncio.to_thread(
                        rag_service.index_message, body.conversation_id, "assistant", full_text
                    )
                except Exception as exc:
                    log.warning("chat.agent_rag_index_failed", error=str(exc))
                try:
                    from app.services import memory_service
                    asyncio.create_task(
                        memory_service.extract_from_text(body.message, body.conversation_id)
                    )
                except Exception as exc:
                    log.debug("chat.agent_memory_extract_spawn_failed", error=str(exc))
                if not getattr(request.app.state, "_titled_for", None):
                    request.app.state._titled_for = set()
                if body.conversation_id not in request.app.state._titled_for:
                    request.app.state._titled_for.add(body.conversation_id)
                    try:
                        from app.services.title_service import maybe_generate_title
                        maybe_generate_title(body.conversation_id, full_text)
                    except Exception as exc:
                        log.debug("chat.agent_title_gen_failed", error=str(exc))
                yield _sse({"type": "done", "checkpointed": ev.get("checkpointed", False)})
            else:
                yield _sse(ev)
    except Exception as exc:
        log.error("chat.agent_turn_failed", error=str(exc))
        yield _sse({"type": "error", "message": str(exc)})


async def _research_event_gen(body: ChatRequest, request: Request) -> AsyncIterator[str]:
    """Same shape as _agent_event_gen but drives research_service's
    web-only loop — no tool_pending/tool_denied ever happens here since
    web_search/fetch_url don't need approval."""
    from app.services import research_service

    history_last_model = None
    try:
        last_msgs = storage.get_messages(body.conversation_id)
        for m in reversed(last_msgs):
            if m.get("model"):
                history_last_model = m["model"]
                break
    except Exception:
        history_last_model = getattr(request.app.state, "last_route_model", None)

    collected_sources: list[dict] = []
    try:
        async for ev in research_service.run_deep_research(
            body.conversation_id, body.message, body.attachment_ids,
            history_last_model=history_last_model,
        ):
            etype = ev.get("type")
            if etype == "sources":
                collected_sources = ev.get("sources", [])
            if etype == "done":
                full_text = ev["full_text"]
                if not full_text.strip():
                    yield _sse({"type": "error", "message": "Empty response."})
                    return
                storage.add_message(
                    body.conversation_id, "assistant", full_text,
                    model=ev.get("model"), route_role=ev.get("role"), route_reason=ev.get("reason"),
                    parent_id=ev.get("parent_id"),
                )
                try:
                    from app.services import rag_service
                    await asyncio.to_thread(
                        rag_service.index_message, body.conversation_id, "assistant", full_text
                    )
                except Exception as exc:
                    log.warning("chat.research_rag_index_failed", error=str(exc))
                try:
                    report = storage.create_research_report(
                        body.conversation_id, body.message, full_text, collected_sources
                    )
                    yield _sse({"type": "research_report_saved", "report_id": report["id"]})
                except Exception as exc:
                    log.warning("chat.research_report_save_failed", error=str(exc))
                try:
                    from app.services import memory_service
                    asyncio.create_task(
                        memory_service.extract_from_text(body.message, body.conversation_id)
                    )
                except Exception as exc:
                    log.debug("chat.research_memory_extract_spawn_failed", error=str(exc))
                if not getattr(request.app.state, "_titled_for", None):
                    request.app.state._titled_for = set()
                if body.conversation_id not in request.app.state._titled_for:
                    request.app.state._titled_for.add(body.conversation_id)
                    try:
                        from app.services.title_service import maybe_generate_title
                        maybe_generate_title(body.conversation_id, full_text)
                    except Exception as exc:
                        log.debug("chat.research_title_gen_failed", error=str(exc))
                yield _sse({"type": "done"})
            else:
                yield _sse(ev)
    except Exception as exc:
        log.error("chat.research_turn_failed", error=str(exc))
        yield _sse({"type": "error", "message": str(exc)})


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


async def _with_heartbeat(stream: AsyncIterator[str], interval: float) -> AsyncIterator[str | None]:
    """Re-yields `stream`, interleaving a `None` whenever `interval` seconds
    pass without a token (the caller turns that into an SSE comment frame).

    The pending read is kept alive across heartbeat ticks (asyncio.wait,
    not wait_for) — cancelling `__anext__` on timeout would tear down the
    underlying Ollama stream."""
    it = stream.__aiter__()
    pending: asyncio.Future | None = None
    while True:
        if pending is None:
            pending = asyncio.ensure_future(it.__anext__())
        done, _ = await asyncio.wait({pending}, timeout=interval if interval > 0 else None)
        if not done:
            yield None
            continue
        task, pending = pending, None
        try:
            yield task.result()
        except StopAsyncIteration:
            return

@router.get("/calendar/events")
async def list_calendar_events(from_ts: float | None = None, to_ts: float | None = None):
    return storage.list_calendar_events(from_ts, to_ts)


@router.post("/calendar/events")
async def create_calendar_event(body: dict):
    title = str(body.get("title", "")).strip()
    start_ts = body.get("start_ts")
    if not title or start_ts is None:
        raise HTTPException(422, "title and start_ts are required.")
    return storage.create_calendar_event(
        title, float(start_ts), body.get("end_ts"), body.get("description", ""),
        bool(body.get("all_day", False)), body.get("source_conversation_id"),
    )


@router.delete("/calendar/events/{event_id}")
async def remove_calendar_event(event_id: str):
    storage.delete_calendar_event(event_id)
    return {"ok": True}


@router.get("/notes")
async def list_notes():
    return storage.list_notes()


@router.post("/notes")
async def create_note(body: dict):
    content = str(body.get("content", "")).strip()
    if not content:
        raise HTTPException(422, "content is required.")
    return storage.create_note(content, body.get("color", "default"))


@router.patch("/notes/{note_id}")
async def update_note(note_id: str, body: dict):
    storage.update_note(note_id, body.get("content"), body.get("color"), body.get("pinned"))
    return {"ok": True}


@router.delete("/notes/{note_id}")
async def remove_note(note_id: str):
    storage.delete_note(note_id)
    return {"ok": True}


@router.get("/todos")
async def list_todos():
    return storage.list_todos()


@router.post("/todos")
async def create_todo(body: dict):
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(422, "text is required.")
    status = body.get("status", "todo")
    if status not in storage.TODO_STATUSES:
        raise HTTPException(422, f"status must be one of {storage.TODO_STATUSES}")
    return storage.create_todo(text, body.get("due_ts"), status)


@router.patch("/todos/{todo_id}")
async def update_todo(todo_id: str, body: dict):
    due_ts = body["due_ts"] if "due_ts" in body else "__unset__"
    status = body.get("status")
    if status is not None and status not in storage.TODO_STATUSES:
        raise HTTPException(422, f"status must be one of {storage.TODO_STATUSES}")
    storage.update_todo(todo_id, body.get("text"), body.get("done"), due_ts, status)
    return {"ok": True}


@router.delete("/todos/{todo_id}")
async def remove_todo(todo_id: str):
    storage.delete_todo(todo_id)
    return {"ok": True}


@router.get("/research/reports")
async def list_research_reports():
    return storage.list_research_reports()


@router.get("/research/reports/{report_id}")
async def get_research_report(report_id: str):
    report = storage.get_research_report(report_id)
    if not report:
        raise HTTPException(404, "No such report.")
    return report


@router.delete("/research/reports/{report_id}")
async def remove_research_report(report_id: str):
    storage.delete_research_report(report_id)
    return {"ok": True}


@router.post("/research/reports/{report_id}/ask")
async def ask_research_report(report_id: str, body: dict):
    """Follow-up question against a saved report — grounded in the
    original answer + sources, not a fresh unscoped chat turn."""
    report = storage.get_research_report(report_id)
    if not report:
        raise HTTPException(404, "No such report.")
    question = str(body.get("question", "")).strip()
    if not question:
        raise HTTPException(422, "question is required.")

    from app.services.router import ModelRegistry, ModelRouter
    registry = ModelRegistry()
    installed = await registry.models()
    router_ = ModelRouter(registry=registry)
    model = router_._match_capability("general", installed) or (installed[0] if installed else None)  # noqa: SLF001
    if not model:
        raise HTTPException(503, "No local model available.")

    sources_block = "\n".join(f"- {s.get('title', '')}: {s.get('url', '')}" for s in report["sources"])
    prompt = (
        f"You previously researched: {report['query']}\n\n"
        f"Your findings:\n{report['answer']}\n\n"
        f"Sources:\n{sources_block}\n\n"
        f"Follow-up question: {question}\n\n"
        "Answer using the research above; say so if it doesn't cover the question."
    )
    answer = await OllamaClient().chat(model, [{"role": "user", "content": prompt}])
    return {"answer": answer}


@router.patch("/conversations/{conversation_id}/group-personas")
async def set_group_personas(conversation_id: str, body: dict):
    persona_ids = body.get("persona_ids") or None
    if persona_ids is not None and len(persona_ids) > 6:
        raise HTTPException(422, "Up to 6 personas per group chat.")
    storage.set_group_personas(conversation_id, persona_ids)
    return {"ok": True, "persona_ids": persona_ids or []}


@router.get("/conversations/{conversation_id}/group-personas")
async def get_group_personas(conversation_id: str):
    return {"persona_ids": storage.get_group_personas(conversation_id)}


@router.post("/conversations/{conversation_id}/group-chat")
async def group_chat(conversation_id: str, body: dict):
    """SSE stream of a simulated multi-bot round: each configured persona
    replies in turn, seeing what the others already said this round."""
    from app.services import group_chat_service

    persona_ids = storage.get_group_personas(conversation_id)
    message = str(body.get("message", "")).strip()

    async def stream():
        if not message:
            yield _sse({"type": "error", "message": "Empty message."})
            return
        try:
            async for ev in group_chat_service.run_group_turn(conversation_id, message, persona_ids):
                yield _sse(ev)
        except Exception as exc:
            log.error("chat.group_chat_failed", error=str(exc))
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(stream(), media_type="text/event-stream")
