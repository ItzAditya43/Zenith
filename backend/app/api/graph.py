"""Knowledge graph: what's actually connected to what across
conversations, projects, memories, and documents — the cross-conversation
memory/recall system is otherwise invisible (it just quietly improves
answers), so this makes the structure it's built on visible.

Read-only, built from real foreign-key relationships already in the
schema (memories.source_conversation_id / project_id, attachments.
conversation_id, conversations.project_id) — not a fabricated or inferred
graph.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.db import storage

router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/graph")
async def knowledge_graph():
    from app.services import memory_service

    conversations = storage.list_conversations()
    projects = storage.list_projects()
    memories = memory_service.list_memories(include_disabled=False)
    attachments = storage.list_all_attachments()

    conv_ids = {c["id"] for c in conversations}
    project_ids = {p["id"] for p in projects}

    nodes = []
    edges = []

    for p in projects:
        nodes.append({"id": f"project:{p['id']}", "type": "project", "label": p["name"]})

    for c in conversations:
        nodes.append({"id": f"conversation:{c['id']}", "type": "conversation", "label": c["title"]})
        if c.get("project_id") and c["project_id"] in project_ids:
            edges.append({"from": f"conversation:{c['id']}", "to": f"project:{c['project_id']}", "kind": "in_project"})

    for m in memories:
        label = m["content"][:80] + ("…" if len(m["content"]) > 80 else "")
        nodes.append({"id": f"memory:{m['id']}", "type": "memory", "label": label})
        src = m.get("source_conversation_id")
        if src and src in conv_ids:
            edges.append({"from": f"memory:{m['id']}", "to": f"conversation:{src}", "kind": "extracted_from"})
        proj = m.get("project_id")
        if proj and proj in project_ids:
            edges.append({"from": f"memory:{m['id']}", "to": f"project:{proj}", "kind": "scoped_to"})

    for a in attachments:
        if a["conversation_id"] not in conv_ids:
            continue
        nodes.append({"id": f"document:{a['id']}", "type": "document", "label": a["filename"]})
        edges.append({"from": f"document:{a['id']}", "to": f"conversation:{a['conversation_id']}", "kind": "attached_to"})

    return {"nodes": nodes, "edges": edges}
