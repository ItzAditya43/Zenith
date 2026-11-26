from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger
from app.core.rate_limit import conversation_lock
from app.db import storage
from app.models.schemas import (
    ChatRequest,
    ConversationBulk,
    ConversationCreate,
    ConversationPersonaSet,
    ConversationRename,
    ConversationWorkdirSet,
    CouncilRequest,
    PersonaCreate,
    PersonaUpdate,
)
from app.services import summary_service, trace_service
from app.services.ollama_client import OllamaClient, OllamaError, ThinkingDelta
from app.services.orchestrator import run_turn
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


@router.post("/conversations/bulk")
async def bulk_conversations(body: ConversationBulk):
    """Apply one action to many chats: pin, unpin, archive, unarchive,
    tag, untag, or delete."""
    action = body.action
    if action not in ("pin", "unpin", "archive", "unarchive", "tag", "untag", "delete"):
        raise HTTPException(400, "Unknown action.")
    if action in ("tag", "untag") and not (body.tag or "").strip():
        raise HTTPException(400, "Name the tag.")
    done = 0
    for cid in body.ids:
        conv = storage.get_conversation(cid)
        if not conv:
            continue
        if action in ("pin", "unpin"):
            storage.set_conversation_pinned(cid, action == "pin")
        elif action in ("archive", "unarchive"):
            storage.set_conversations_archived([cid], action == "archive")
        elif action in ("tag", "untag"):
            tag = body.tag.strip()
            tags = [t for t in conv.get("tags", []) if t != tag]
            if action == "tag":
                tags.append(tag)
            storage.set_conversation_tags(cid, tags[:20])
        elif action == "delete":
            try:
                from app.services.attachments import cleanup_for_conversation
                await asyncio.to_thread(cleanup_for_conversation, cid)
            except Exception as exc:
                log.warning("chat.bulk_delete_cleanup_failed", error=str(exc))
            storage.delete_conversation(cid)
        done += 1
    return {"ok": True, "count": done}


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


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, body: dict):
    """Edit a project's name, folder, default persona or instructions."""
    if body.get("persona_id"):
        from app.services import persona_service
        if not persona_service.get_persona(body["persona_id"]):
            raise HTTPException(404, "No such persona.")
    project = storage.update_project(project_id, body)
    if project is None:
        raise HTTPException(404, "No such project.")
    return project


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


class ShareBody(BaseModel):
    redact: list[dict] = []
    exclude_message_ids: list[str] = []
    include_attachments: bool = False


@router.get("/conversations/{conversation_id}/share/preview")
async def share_preview(conversation_id: str):
    """The messages that could be shared and the sensitive-looking text in them."""
    from app.services import share_service

    if not storage.get_conversation(conversation_id):
        raise HTTPException(404, "No such conversation.")
    return await asyncio.to_thread(share_service.preview, conversation_id)


@router.post("/conversations/{conversation_id}/share")
async def share_conversation(conversation_id: str, body: ShareBody | None = None):
    """Share a redacted snapshot: later messages never appear on the link,
    and resharing replaces the old link."""
    from app.services import share_service

    body = body or ShareBody()
    try:
        token = await asyncio.to_thread(share_service.create_snapshot, conversation_id, body.redact,
                                        body.exclude_message_ids, body.include_attachments)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"token": token}


@router.post("/conversations/{conversation_id}/share/export")
async def share_export(conversation_id: str, body: ShareBody, format: str = "markdown"):
    """The same redacted copy as a file, without creating a link."""
    from fastapi.responses import JSONResponse, PlainTextResponse

    from app.services import share_service

    try:
        snap = await asyncio.to_thread(share_service.build, conversation_id, body.redact,
                                       body.exclude_message_ids, body.include_attachments)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    slug = "".join(ch if ch.isalnum() else "-" for ch in snap["title"].lower()).strip("-")[:60] or "conversation"
    if format == "json":
        return JSONResponse(snap, headers={"Content-Disposition": f'attachment; filename="{slug}.json"'})
    return PlainTextResponse(share_service.to_markdown(snap), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{slug}.md"'})


@router.delete("/conversations/{conversation_id}/share")
async def unshare_conversation(conversation_id: str):
    from app.services import share_service

    storage.revoke_share_link(conversation_id)
    share_service.revoke(conversation_id)
    return {"ok": True}


@router.get("/share/{token}")
async def view_shared_conversation(token: str):
    """Public, read-only — deliberately not behind the passcode-lock
    middleware (see main.py's lock allowlist) so a link works for anyone
    it's sent to. Serves the redacted snapshot taken when the link was
    made; links created before snapshots existed still show the live chat."""
    from app.services import share_service

    snap = share_service.get_snapshot(token)
    if snap:
        return snap
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
    """Each action carries its template `fields` ({{name|default}}) so the
    UI can ask for them before sending."""
    from app.services import packs_service

    out = []
    for q in storage.list_quick_actions():
        try:
            q["fields"] = packs_service.template_fields(q["prompt_template"])
        except ValueError:
            q["fields"] = []
        out.append(q)
    return out


@router.post("/quick-actions/render")
async def render_quick_action(body: dict):
    """Fill a template's fields: {template, values}."""
    from app.services import packs_service

    tpl = str(body.get("template") or "")
    try:
        packs_service.template_fields(tpl)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"text": packs_service.fill_template(tpl, {str(k): str(v) for k, v in (body.get("values") or {}).items()})}


@router.get("/packs/export")
async def export_pack(name: str = "My Zenith pack", description: str = "", quick_actions: str | None = None,
                      personas: str | None = None, rules: str | None = None):
    """A shareable pack. Each list param is comma-separated ids; omitted
    means all of that kind, an empty string means none."""
    from fastapi.responses import JSONResponse

    from app.services import packs_service

    def ids(v):
        return None if v is None else [x for x in v.split(",") if x]

    pack = packs_service.export_pack(name, description, ids(quick_actions), ids(personas), ids(rules))
    slug = "".join(ch if ch.isalnum() else "-" for ch in pack["name"].lower()).strip("-") or "pack"
    return JSONResponse(pack, headers={"Content-Disposition": f'attachment; filename="{slug}.zenith-pack.json"'})


@router.post("/packs/preview")
async def preview_pack(body: dict):
    from app.services import packs_service

    try:
        return packs_service.preview_pack(body.get("pack"))
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, str(exc) or "That pack couldn't be read.") from exc


@router.post("/packs/import")
async def import_pack(body: dict):
    from app.services import packs_service

    include = body.get("include")
    try:
        return packs_service.import_pack(body.get("pack"), include if isinstance(include, list) else None)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, str(exc) or "That pack couldn't be imported.") from exc


@router.post("/quick-actions")
async def create_quick_action(body: dict):
    name = str(body.get("name", "")).strip()
    prompt_template = str(body.get("prompt_template", "")).strip()
    if not name or not prompt_template:
        raise HTTPException(422, "name and prompt_template are required.")
    from app.services import packs_service
    try:
        fields = packs_service.template_fields(prompt_template)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = storage.create_quick_action(name[:100], prompt_template[:5000], bool(body.get("auto_send")))
    return {**row, "fields": fields}


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


@router.get("/conversations/{conversation_id}/state")
async def get_conversation_state(conversation_id: str):
    """The compacted state of this conversation's older messages."""
    if not storage.get_conversation(conversation_id):
        raise HTTPException(404, "Conversation not found")
    return await asyncio.to_thread(summary_service.inspect, conversation_id)


class StateEdit(BaseModel):
    state: dict


@router.put("/conversations/{conversation_id}/state")
async def edit_conversation_state(conversation_id: str, body: StateEdit):
    if not storage.get_conversation(conversation_id):
        raise HTTPException(404, "Conversation not found")
    return await asyncio.to_thread(summary_service.save_edit, conversation_id, body.state)


@router.post("/conversations/{conversation_id}/state/regenerate")
async def regenerate_conversation_state(conversation_id: str):
    """Rebuild from the source messages; pinned items are kept."""
    if not storage.get_conversation(conversation_id):
        raise HTTPException(404, "Conversation not found")
    ok = await summary_service.update(conversation_id, force=True)
    out = await asyncio.to_thread(summary_service.inspect, conversation_id)
    out["regenerated"] = ok
    return out


@router.delete("/conversations/{conversation_id}/state")
async def clear_conversation_state(conversation_id: str):
    await asyncio.to_thread(summary_service.clear, conversation_id)
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
            trace_service.start(body.conversation_id, "agent", body.message)
            try:
                async with conversation_lock(body.conversation_id):
                    async for ev in _agent_event_gen(body, request):
                        yield ev
            except TimeoutError as exc:
                yield _sse({"type": "error", "message": str(exc)})

        return StreamingResponse(agent_guarded_gen(), media_type="text/event-stream")

    if body.deep_research:
        async def research_guarded_gen():
            trace_service.start(body.conversation_id, "research", body.message)
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
    regenerate_user_message_id = None
    if body.regenerate_of:
        regen_msg = storage.get_message(body.regenerate_of)
        if not regen_msg or not regen_msg.get("parent_id"):
            raise HTTPException(404, "No such message to regenerate.")
        storage.deactivate_subtree(regen_msg["parent_id"])
        regenerate_user_message_id = regen_msg["parent_id"]

    try:
        decision, stream, web_sources, assistant_parent_id = await run_turn(
            body.conversation_id, body.message, body.attachment_ids,
            history_last_model=history_last_model,
            web_search=body.web_search,
            parent_message_id=parent_message_id,
            parent_explicit=parent_explicit,
            emit_thinking=True,
            regenerate_user_message_id=regenerate_user_message_id,
            model_override=body.model_override,
        )
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    heartbeat = int(settings.get("sse_heartbeat_seconds", 15))
    max_idle = float(settings.get("stream_idle_timeout_seconds", 120))

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
        post_reply: tuple[str, str] | None = None
        turn_start = time.monotonic()
        first_token_ms: int | None = None
        try:
            async with conversation_lock(key):
                try:
                    async for piece in _with_heartbeat(stream, heartbeat, max_idle):
                        if piece is None:
                            continue  # heartbeats aren't replayed — a resumer doesn't need them
                        if isinstance(piece, ThinkingDelta):
                            # Reasoning from a thinking model: streamed so the UI
                            # can show it live, never persisted as the reply.
                            await registry.publish(key, _sse({"type": "thinking", "text": str(piece)}))
                            continue
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
                                async for piece in _with_heartbeat(retry_stream, heartbeat, max_idle):
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
                    storage.record_usage_event(
                        current_model, current_role, len(collected),
                        int((time.monotonic() - turn_start) * 1000), first_token_ms,
                    )
                except Exception as exc:
                    log.debug("chat.usage_record_failed", error=str(exc))
                # Post-reply work (embedding the reply, memory extraction —
                # an LLM call — and title generation) used to run here, BEFORE
                # "done" and inside the conversation lock: the UI stayed
                # "generating" for minutes on slow hardware and the next message
                # queued behind it. Now it runs after the lock is released.
                post_reply = (key, full_text)
                await registry.publish(key, _sse({"type": "done"}))
        except TimeoutError as exc:
            await registry.publish(key, _sse({"type": "error", "message": str(exc)}))
        except Exception as exc:
            log.error("chat.produce_failed", error=str(exc))
            await registry.publish(key, _sse({"type": "error", "message": str(exc)}))
        finally:
            await registry.finish(key)
            registry.cleanup_later(key)
        if post_reply:
            asyncio.create_task(_after_reply(request, body.message, *post_reply))

    async def event_gen():
        # Bound before produce() is spawned, so that task (which publishes the
        # tokens and the final done/error) inherits this trace.
        trace_service.start(body.conversation_id, "chat", body.message)
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
    from app.services import model_health
    from app.services.router import is_cloud_model

    cfg = settings.get("fallback_model", "general")
    if not cfg:
        return None
    pick = await _resolve_fallback(request, current_model, cfg)
    # The fallback is the safety net, so it must be something that can run:
    # never a model Ollama just refused, and never a cloud model unless the
    # user allowed cloud routing.
    if pick and not model_health.is_unavailable(pick) and (
        not is_cloud_model(pick) or settings.get("route_to_cloud_models", False)
    ):
        return pick
    try:
        from app.services.router import ModelRegistry
        installed = [n for n in await ModelRegistry().models()
                     if n != current_model and not is_cloud_model(n) and not model_health.is_unavailable(n)]
        router_ = ModelRouter(registry=ModelRegistry())
        for role in ("general", "small_fast"):
            m = router_._match_capability(role, installed)  # noqa: SLF001
            if m and m != current_model and not is_cloud_model(m):
                return m
    except Exception as exc:
        log.warning("chat.fallback_resolve_failed", error=str(exc))
    return None


async def _resolve_fallback(request: Request, current_model: str, cfg: str) -> str | None:
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


async def _after_reply(request: Request, user_text: str, key: str, full_text: str) -> None:
    """Best-effort follow-ups to a finished plain-chat turn, run in the
    background after the stream has ended and the lock is free."""
    try:
        from app.services import rag_service
        await asyncio.to_thread(rag_service.index_message, key, "user", user_text)
        await asyncio.to_thread(rag_service.index_message, key, "assistant", full_text)
    except Exception as exc:
        log.warning("chat.rag_index_failed", error=str(exc))
    try:
        from app.services import memory_service
        added = await memory_service.extract_from_text(user_text, key)
        if added:
            log.info("chat.memories_saved", count=len(added))
    except Exception as exc:
        log.debug("chat.memory_extract_failed", error=str(exc))
    try:
        from app.services import summary_service
        await summary_service.update(key)
    except Exception as exc:
        log.debug("chat.summary_update_failed", error=str(exc))
    if not getattr(request.app.state, "_titled_for", None):
        request.app.state._titled_for = set()
    if key not in request.app.state._titled_for:
        request.app.state._titled_for.add(key)
        try:
            from app.services.title_service import maybe_generate_title
            maybe_generate_title(key, full_text)
        except Exception as exc:
            log.debug("chat.title_gen_failed", error=str(exc))


def _sse(payload: dict[str, Any]) -> str:
    trace_service.observe(payload)
    return f"data: {json.dumps(payload)}\n\n"


async def _with_heartbeat(
    stream: AsyncIterator[str], interval: float, max_idle_seconds: float | None = None,
) -> AsyncIterator[str | None]:
    """Live-reply bookkeeping around `_heartbeat_stream` (background
    re-embedding pauses while any reply is streaming)."""
    from app.services import rag_service

    with rag_service.live_reply():
        async for piece in _heartbeat_stream(stream, interval, max_idle_seconds):
            yield piece


async def _heartbeat_stream(
    stream: AsyncIterator[str], interval: float, max_idle_seconds: float | None = None,
) -> AsyncIterator[str | None]:
    """Re-yields `stream`, interleaving a `None` whenever `interval` seconds
    pass without a token (the caller turns that into an SSE comment frame).

    The pending read is kept alive across heartbeat ticks (asyncio.wait,
    not wait_for) — cancelling `__anext__` on timeout would tear down the
    underlying Ollama stream.

    If `max_idle_seconds` is set and that much *total* idle time accumulates
    with no token at all (not total generation time — a long reply that's
    still actively streaming never trips this), the pending read is
    cancelled and a TimeoutError raised. This is the fix for a real failure
    mode: a model that's swapped out of VRAM and effectively hung (partial
    CPU offload thrashing, or genuinely wedged) used to hold the
    per-conversation lock forever, silently blocking every subsequent
    message in that conversation behind a request that would never finish."""
    it = stream.__aiter__()
    pending: asyncio.Future | None = None
    idle_elapsed = 0.0
    while True:
        if pending is None:
            pending = asyncio.ensure_future(it.__anext__())
        tick = interval if interval > 0 else None
        done, _ = await asyncio.wait({pending}, timeout=tick)
        if not done:
            idle_elapsed += tick or 0
            if max_idle_seconds and idle_elapsed >= max_idle_seconds:
                pending.cancel()
                raise TimeoutError(
                    f"No response from the model for {int(max_idle_seconds)}s — it may be "
                    "stuck (a common cause: a model too large for your GPU, spilling onto "
                    "slow CPU inference). Try a smaller model in Settings -> Model routing."
                )
            yield None
            continue
        idle_elapsed = 0.0
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
    before = next((t for t in storage.list_todos() if t["id"] == todo_id), None)
    storage.update_todo(todo_id, body.get("text"), body.get("done"), due_ts, status)
    after = next((t for t in storage.list_todos() if t["id"] == todo_id), None)
    if before and after and not before.get("done") and after.get("done"):
        from app.services import events
        await events.emit("todo_completed", {"id": todo_id, "text": after["text"]})
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
