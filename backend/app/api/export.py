"""Full data export — the "this is actually yours" feature. Everything
Zenith knows (conversations, messages, memories, personas) as either one
complete JSON file or a human-readable Markdown zip, no partial/opaque
formats. No external dependencies: stdlib json/zipfile only.
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile

from fastapi import APIRouter
from fastapi.responses import Response, StreamingResponse

from app.db import storage
from app.services import memory_service, persona_service

router = APIRouter(prefix="/api/export", tags=["export"])


def _safe_filename(title: str, fallback: str) -> str:
    name = re.sub(r"[^\w\- ]", "", title or "").strip() or fallback
    return name[:80]


def _full_dump() -> dict:
    conversations = storage.list_conversations()
    for c in conversations:
        c["messages"] = storage.get_messages(c["id"])
    return {
        "exported_at": time.time(),
        "conversations": conversations,
        "memories": memory_service.list_memories(),
        "personas": persona_service.list_personas(),
    }


@router.get("/json")
async def export_json():
    payload = json.dumps(_full_dump(), indent=2, default=str)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="zenith-export.json"'},
    )


def _conversation_to_markdown(conv: dict) -> str:
    lines = [f"# {conv['title']}", ""]
    for m in conv["messages"]:
        role = m["role"].capitalize()
        lines.append(f"## {role}" + (f" ({m['model']})" if m.get("model") else ""))
        lines.append("")
        lines.append(m["content"])
        if m.get("attachments"):
            names = ", ".join(a.get("name", "?") for a in m["attachments"])
            lines.append(f"\n*Attachments: {names}*")
        lines.append("")
    return "\n".join(lines)


@router.get("/markdown")
async def export_markdown():
    dump = _full_dump()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        used_names: set[str] = set()
        for conv in dump["conversations"]:
            base = _safe_filename(conv["title"], conv["id"][:8])
            name = base
            i = 2
            while name in used_names:
                name = f"{base}-{i}"
                i += 1
            used_names.add(name)
            zf.writestr(f"conversations/{name}.md", _conversation_to_markdown(conv))

        if dump["memories"]:
            mem_lines = ["# Memories", ""]
            mem_lines += [f"- {m['content']}" for m in dump["memories"] if m["enabled"]]
            zf.writestr("memories.md", "\n".join(mem_lines))

        if dump["personas"]:
            persona_lines = ["# Personas", ""]
            for p in dump["personas"]:
                persona_lines.append(f"## {p.get('icon', '')} {p['name']}".strip())
                persona_lines.append("")
                persona_lines.append(p["system_prompt"])
                persona_lines.append("")
            zf.writestr("personas.md", "\n".join(persona_lines))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="zenith-export.zip"'},
    )
