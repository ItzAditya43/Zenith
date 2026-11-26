"""Full data export — the "this is actually yours" feature. Everything
Zenith knows (conversations, messages, memories, personas) as either one
complete JSON file or a human-readable Markdown zip, no partial/opaque
formats. No external dependencies: stdlib json/zipfile only.

The one exception is single-conversation PDF export, which needs real
typesetting (word-wrap, fonts) that stdlib doesn't offer. fpdf2 is
pure-Python with zero system dependencies (no Cairo/Pango/headless
browser), matching the project's stdlib-first, fully-local philosophy.
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from fpdf import FPDF

from app.db import storage
from app.services import folder_service, memory_service, persona_service

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
        # Zenith-to-Zenith scope (re-imported by import_zenith_backup):
        # projects (with conversations' project_id remapped on import),
        # quick actions, and watched folders. Schedules are deliberately
        # excluded — see import_service.import_zenith_backup docstring.
        "projects": storage.list_projects(),
        "quick_actions": storage.list_quick_actions(),
        "folders": folder_service.list_watched_folders(),
    }


@router.get("/json")
async def export_json():
    payload = json.dumps(_full_dump(), indent=2, default=str)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="zenith-export.json"'},
    )


def _conversation_to_markdown(conv: dict, metadata: bool = True, attachments: bool = True) -> str:
    """One chat as Markdown. `metadata` adds the model and time to each
    message heading and a provenance line (tags, created); `attachments`
    lists attachment names. Zenith can re-import this format."""
    from datetime import datetime

    lines = [f"# {conv['title']}", ""]
    if metadata:
        made = datetime.fromtimestamp(conv.get("created_at") or 0).strftime("%Y-%m-%d %H:%M")
        tags = ", ".join(conv.get("tags") or [])
        lines += [f"_Created {made}{f' · tags: {tags}' if tags else ''}_", ""]
    for m in conv["messages"]:
        role = m["role"].capitalize()
        head = f"## {role}"
        if metadata:
            extra = [x for x in (m.get("model"), datetime.fromtimestamp(m["created_at"]).strftime("%Y-%m-%d %H:%M") if m.get("created_at") else None) if x]
            if extra:
                head += f" ({' · '.join(extra)})"
        lines.append(head)
        lines.append("")
        lines.append(m["content"])
        if attachments and m.get("attachments"):
            names = ", ".join(a.get("name") or a.get("filename") or "?" for a in m["attachments"])
            lines.append(f"\n*Attachments: {names}*")
        lines.append("")
    return "\n".join(lines)


def _strip_conv(conv: dict, metadata: bool, attachments: bool) -> dict:
    keep_msg = ("role", "content") + (("model", "created_at", "route_role") if metadata else ())
    out = {"title": conv["title"]}
    if metadata:
        out.update({k: conv.get(k) for k in ("id", "created_at", "updated_at", "tags", "pinned")})
    out["messages"] = []
    for m in conv["messages"]:
        mm = {k: m.get(k) for k in keep_msg}
        if attachments and m.get("attachments"):
            mm["attachments"] = [a.get("name") or a.get("filename") for a in m["attachments"]]
        out["messages"].append(mm)
    return out


@router.get("/conversation/{conversation_id}")
async def export_one(conversation_id: str, format: str = "markdown", metadata: bool = True, attachments: bool = True):
    """One chat as Markdown or JSON, with metadata and attachment names on or off."""
    from fastapi import HTTPException

    conv = storage.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "No such conversation.")
    conv["messages"] = storage.get_messages(conversation_id)
    name = _safe_filename(conv["title"], conv["id"][:8])
    if format == "json":
        return Response(json.dumps(_strip_conv(conv, metadata, attachments), indent=2, default=str),
                        media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    return Response(_conversation_to_markdown(conv, metadata, attachments), media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="{name}.md"'})


@router.get("/markdown")
async def export_markdown(metadata: bool = True, attachments: bool = True):
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
            zf.writestr(f"conversations/{name}.md", _conversation_to_markdown(conv, metadata, attachments))

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


def _pdf_safe(text: str) -> str:
    """fpdf2's built-in core fonts (Helvetica/Times/Courier) only cover
    Latin-1 — replace anything outside that range rather than crashing the
    export on an emoji or CJK character (no custom font vendored, by
    design: out of scope for this feature)."""
    return text.encode("latin-1", "replace").decode("latin-1")


def _render_conversation_pdf(conv: dict) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    def line(h: float, text: str, **kwargs) -> None:
        # multi_cell() leaves the cursor at the end of the last line of
        # text (x near the right margin) rather than resetting it — the
        # next call's width then shrinks by that amount and eventually
        # runs out of room. Reset x to the left margin after every call.
        pdf.multi_cell(0, h, text, **kwargs)
        pdf.set_x(pdf.l_margin)

    pdf.set_font("Helvetica", "B", 18)
    line(10, _pdf_safe(conv.get("title") or "Untitled conversation"))
    pdf.ln(2)

    for m in conv.get("messages", []):
        role = (m.get("role") or "").capitalize()
        header = role + (f" ({m['model']})" if m.get("model") else "")
        pdf.set_font("Helvetica", "B", 11)
        pdf.ln(4)
        line(7, _pdf_safe(header))

        content = m.get("content") or ""
        # Split on fenced code blocks (```...```) so code gets a monospace,
        # shaded box while prose stays in the body font.
        parts = re.split(r"```(?:\w+)?\n?(.*?)```", content, flags=re.DOTALL)
        for i, part in enumerate(parts):
            if not part:
                continue
            if i % 2 == 1:
                # Code block.
                pdf.set_font("Courier", "", 9)
                pdf.set_fill_color(240, 240, 240)
                line(5, _pdf_safe(part.strip("\n")), fill=True)
                pdf.set_fill_color(255, 255, 255)
            else:
                pdf.set_font("Times", "", 11)
                line(6, _pdf_safe(part.strip("\n")))

        if m.get("attachments"):
            names = ", ".join(a.get("name", "?") for a in m["attachments"])
            pdf.set_font("Times", "I", 9)
            line(5, _pdf_safe(f"Attachments: {names}"))

    return bytes(pdf.output())


@router.get("/{conversation_id}/pdf")
async def export_conversation_pdf(conversation_id: str):
    conv = storage.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv["messages"] = storage.get_messages(conversation_id)

    pdf_bytes = _render_conversation_pdf(conv)
    filename = _safe_filename(conv["title"], conv["id"][:8])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )
