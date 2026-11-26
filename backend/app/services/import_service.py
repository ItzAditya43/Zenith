"""Import conversation history from other assistants, so past chats aren't
stranded in another tool. All are self-serve exports (no API, no scraping):

- ChatGPT `conversations.json` (a tree of message nodes under `mapping`)
- Claude `conversations.json` (a flat `chat_messages` list)
- Open WebUI chat exports (`[{"chat": {"title", "messages"|"history"}}]`)
- OpenAI-style message lists (`[{"role", "content"}]` or `{"messages": [...]}`),
  which LM Studio, LibreChat and many scripts produce
- Markdown transcripts, including Zenith's own Markdown export and
  "**You:**" / "## User" style files

Every imported chat is tagged with where it came from, and a fingerprint
of its title and messages is kept so importing the same file twice
doesn't create duplicates.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from app.core.logging import get_logger
from app.db import storage

log = get_logger(__name__)


def _parse_ts(value) -> float | None:
    """ChatGPT uses unix floats; Claude uses ISO-8601 strings. Return a unix
    timestamp, or None if it can't be parsed (import still proceeds)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def parse_chatgpt(convos: list) -> list[dict]:
    out = []
    for c in convos:
        if not isinstance(c, dict):
            continue
        title = (c.get("title") or "Imported chat").strip()
        mapping = c.get("mapping") or {}
        msgs = []
        for node in mapping.values():
            if not isinstance(node, dict):
                continue
            m = node.get("message")
            if not isinstance(m, dict):
                continue
            role = (m.get("author") or {}).get("role")
            if role not in ("user", "assistant"):
                continue  # skip system/tool nodes
            content = m.get("content") or {}
            parts = content.get("parts") or []
            text = "\n".join(p for p in parts if isinstance(p, str)).strip()
            if not text:
                continue
            msgs.append({"role": role, "content": text, "created_at": _parse_ts(m.get("create_time"))})
        # ChatGPT's mapping is a tree; ordering by create_time reconstructs
        # the linear conversation for the common (non-branched) case.
        msgs.sort(key=lambda x: x["created_at"] or 0)
        if msgs:
            out.append({"title": title, "messages": msgs})
    return out


def parse_claude(convos: list) -> list[dict]:
    out = []
    for c in convos:
        if not isinstance(c, dict):
            continue
        title = (c.get("name") or "Imported chat").strip()
        msgs = []
        for m in c.get("chat_messages") or []:
            if not isinstance(m, dict):
                continue
            sender = str(m.get("sender") or "")
            role = {"human": "user", "assistant": "assistant"}.get(sender)
            if not role:
                continue
            text = (m.get("text") or "").strip()
            if not text and isinstance(m.get("content"), list):
                text = "\n".join(
                    b.get("text", "") for b in m["content"] if isinstance(b, dict)
                ).strip()
            if not text:
                continue
            msgs.append({"role": role, "content": text, "created_at": _parse_ts(m.get("created_at"))})
        if msgs:
            out.append({"title": title, "messages": msgs})
    return out


def _text_of(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):  # OpenAI content parts
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type", "text") == "text").strip()
    return ""


def _role(r) -> str | None:
    return {"user": "user", "human": "user", "assistant": "assistant", "ai": "assistant", "bot": "assistant",
            "model": "assistant"}.get(str(r or "").lower())


def parse_openai_messages(data) -> list[dict]:
    """A bare message list, or {"messages": [...], "title"?}; or a list of those."""
    if isinstance(data, dict):
        data = [data]
    if data and isinstance(data[0], dict) and "role" in data[0]:
        data = [{"messages": data}]
    out = []
    for c in data:
        if not isinstance(c, dict):
            continue
        msgs = []
        for m in c.get("messages") or []:
            if not isinstance(m, dict):
                continue
            role, text = _role(m.get("role")), _text_of(m.get("content"))
            if role and text:
                msgs.append({"role": role, "content": text, "created_at": _parse_ts(m.get("timestamp") or m.get("created_at"))})
        if msgs:
            out.append({"title": (c.get("title") or msgs[0]["content"][:60] or "Imported chat").strip(), "messages": msgs})
    return out


def parse_open_webui(data: list) -> list[dict]:
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        chat = item.get("chat") or {}
        title = (chat.get("title") or item.get("title") or "Imported chat").strip()
        raw = chat.get("messages")
        if not raw:
            hist = (chat.get("history") or {}).get("messages") or {}
            # Follow the active branch back from currentId when there is one.
            cur = (chat.get("history") or {}).get("currentId")
            chain = []
            while cur and cur in hist:
                chain.append(hist[cur])
                cur = hist[cur].get("parentId")
            raw = list(reversed(chain)) if chain else sorted(hist.values(), key=lambda m: m.get("timestamp") or 0)
        msgs = []
        for m in raw or []:
            if not isinstance(m, dict):
                continue
            role, text = _role(m.get("role")), _text_of(m.get("content"))
            if role and text:
                msgs.append({"role": role, "content": text, "created_at": _parse_ts(m.get("timestamp"))})
        if msgs:
            out.append({"title": title, "messages": msgs})
    return out


_MD_SPEAKER = re.compile(
    r"^(?:#{1,6}\s*|\*\*)?(you|user|human|me|assistant|ai|claude|chatgpt|zenith|bot)(?:\s*\([^)]*\))?\s*:?\s*(?:\*\*)?\s*:?\s*$",
    re.IGNORECASE,
)


def parse_markdown(text: str, fallback_title: str = "Imported chat") -> list[dict]:
    """Speaker headings or bold labels on their own line ("## User",
    "**You:**", "## Assistant (model)") start each message."""
    title = fallback_title
    msgs: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not msgs and cur is None:
            title = stripped[2:].strip() or title
            continue
        m = _MD_SPEAKER.match(stripped)
        if m:
            if cur and cur["content"].strip():
                msgs.append(cur)
            who = m.group(1).lower()
            cur = {"role": "user" if who in ("you", "user", "human", "me") else "assistant", "content": ""}
            continue
        if cur is not None:
            if stripped.startswith("_Attachments:") or stripped.startswith("*Attachments:"):
                continue
            cur["content"] += line + "\n"
    if cur and cur["content"].strip():
        msgs.append(cur)
    for m in msgs:
        m["content"] = m["content"].strip()
    return [{"title": title, "messages": msgs}] if msgs else []


def detect_and_parse(data) -> list[dict]:
    """Sniff ChatGPT vs Claude from the shape and normalize. Accepts either a
    list of conversations or a single conversation object."""
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ValueError("Export is empty or not a list of conversations.")
    sample = next((x for x in data if isinstance(x, dict)), None)
    if sample is None:
        raise ValueError("No conversation objects found in the export.")
    if "mapping" in sample:
        return parse_chatgpt(data)
    if "chat_messages" in sample:
        return parse_claude(data)
    if isinstance(sample.get("chat"), dict):
        return parse_open_webui(data)
    if "role" in sample or "messages" in sample:
        return parse_openai_messages(data)
    raise ValueError(
        "Unrecognized export — expected ChatGPT, Claude, Open WebUI, an OpenAI-style message list, or Markdown."
    )


def source_of(data) -> str:
    sample = data[0] if isinstance(data, list) and data else data
    if not isinstance(sample, dict):
        return "import"
    if "mapping" in sample:
        return "chatgpt"
    if "chat_messages" in sample:
        return "claude"
    if isinstance(sample.get("chat"), dict):
        return "open-webui"
    return "openai-format"


def fingerprint(conv: dict) -> str:
    h = hashlib.sha256()
    h.update((conv.get("title") or "").encode())
    for m in conv["messages"][:50]:
        h.update(b"\x00" + m["role"].encode() + b"\x01" + m["content"][:2000].encode())
    return h.hexdigest()[:32]


def is_zenith_backup(data) -> bool:
    """Sniff Zenith's own /api/export/json shape, so it can be routed to
    import_zenith_backup instead of the ChatGPT/Claude parsers."""
    return (
        isinstance(data, dict)
        and "conversations" in data
        and isinstance(data.get("conversations"), list)
        and ("memories" in data or "personas" in data)
    )


def import_zenith_backup(data: dict) -> dict:
    """Re-import a full Zenith export (from /api/export/json) — the
    Zenith-to-Zenith counterpart to the ChatGPT/Claude importers above.
    Conversations/messages, projects, quick actions, and watched folders
    always create new rows (so importing twice just duplicates them, same
    as re-importing a ChatGPT export would); memories and personas dedupe
    via their own service-layer logic so re-running an import is safe.

    Schedules are deliberately NOT re-imported: a schedule is a live cron
    trigger bound to a specific model + (often) a specific conversation on
    the source instance. Blindly recreating it on a different instance
    risks firing autonomous turns against a model that isn't installed
    there, or a conversation id that no longer resolves — silent failure
    or, worse, an unexpected autonomous run. Re-creating a schedule is a
    deliberate, low-frequency action better left to the user via
    Settings -> Schedules on the new instance.
    """
    from app.services import folder_service, memory_service, persona_service

    # Projects first, so conversations below can remap their project_id
    # from the source instance's id to the id newly created here — the
    # same id-remap pattern used for message parent_id further down.
    projects = 0
    project_id_map: dict[str, str] = {}
    for proj in data.get("projects") or []:
        if not isinstance(proj, dict) or not proj.get("name"):
            continue
        new_proj = storage.create_project(proj["name"], workdir=proj.get("workdir"))
        if proj.get("id"):
            project_id_map[proj["id"]] = new_proj["id"]
        projects += 1

    conversations = 0
    messages = 0
    for conv in data.get("conversations") or []:
        if not isinstance(conv, dict):
            continue
        title = (conv.get("title") or "Imported chat")[:200]
        new_project_id = project_id_map.get(str(conv.get("project_id") or ""))
        c = storage.create_conversation(title, project_id=new_project_id)
        id_map: dict[str, str] = {}
        for m in conv.get("messages") or []:
            if not isinstance(m, dict) or not m.get("role") or not m.get("content"):
                continue
            old_parent = str(m.get("parent_id") or "")
            new_msg = storage.add_message(
                c["id"], m["role"], m["content"],
                parent_id=id_map.get(old_parent), created_at=_parse_ts(m.get("created_at")),
            )
            if m.get("id"):
                id_map[m["id"]] = new_msg["id"]
            messages += 1
        conversations += 1

    memories = 0
    for mem in data.get("memories") or []:
        if isinstance(mem, dict) and mem.get("content"):
            if memory_service.add_memory(mem["content"], category=mem.get("category", "fact")):
                memories += 1

    personas = 0
    # persona_service.create_persona has no dedup of its own (unlike
    # add_memory) — re-running an import would otherwise duplicate every
    # persona on each pass, so dedupe here on (name, system_prompt).
    existing_personas = {
        (ep["name"], ep["system_prompt"]) for ep in persona_service.list_personas()
    }
    for p in data.get("personas") or []:
        if isinstance(p, dict) and p.get("name") and p.get("system_prompt"):
            key = (p["name"].strip(), p["system_prompt"].strip())
            if key in existing_personas:
                continue
            persona_service.create_persona(p["name"], p["system_prompt"], icon=p.get("icon"))
            existing_personas.add(key)
            personas += 1

    quick_actions = 0
    for qa in data.get("quick_actions") or []:
        if isinstance(qa, dict) and qa.get("name") and qa.get("prompt_template"):
            storage.create_quick_action(
                qa["name"], qa["prompt_template"], bool(qa.get("auto_send", False))
            )
            quick_actions += 1

    folders = 0
    for f in data.get("folders") or []:
        if not isinstance(f, dict) or not f.get("path"):
            continue
        try:
            folder_service.add_watched_folder(f["path"], f.get("extensions"))
            folders += 1
        except ValueError:
            # Path doesn't exist on this machine, or is already watched —
            # a folder's path is inherently machine-specific, so skipping
            # it is expected rather than a reason to fail the whole import.
            pass

    return {
        "conversations": conversations, "messages": messages, "memories": memories,
        "personas": personas, "projects": projects, "quick_actions": quick_actions,
        "folders": folders,
    }


def _seen_fingerprints() -> set[str]:
    from app.db.storage import _conn

    with _conn() as conn:
        return {r[0] for r in conn.execute("SELECT fingerprint FROM import_fingerprints")}


def import_conversations(parsed: list[dict], source: str = "import") -> dict:
    """Create Zenith conversations from normalized data. Messages are chained
    linearly (each is the previous one's child) to match the branching
    model's active-chain shape. Chats already imported (same title and
    messages) are skipped; each new one is tagged "imported" and with its
    source."""
    from app.db.storage import _conn

    conversations = 0
    messages = 0
    skipped = 0
    seen = _seen_fingerprints()
    for conv in parsed:
        fp = fingerprint(conv)
        if fp in seen:
            skipped += 1
            continue
        seen.add(fp)
        title = (conv["title"] or "Imported chat")[:200]
        c = storage.create_conversation(title)
        storage.set_conversation_tags(c["id"], ["imported", source])
        with _conn() as conn:
            conn.execute("INSERT OR IGNORE INTO import_fingerprints (fingerprint, conversation_id, source, imported_at)"
                         " VALUES (?, ?, ?, strftime('%s','now'))", (fp, c["id"], source))
        prev_id = None
        for m in conv["messages"]:
            msg = storage.add_message(
                c["id"], m["role"], m["content"],
                parent_id=prev_id, created_at=m.get("created_at"),
            )
            prev_id = msg["id"]
            messages += 1
        conversations += 1
    return {"conversations": conversations, "messages": messages, "skipped_duplicates": skipped}
