"""Import conversation history exported from ChatGPT or Claude, so a user's
past chats aren't stranded in another tool. Both are self-serve data exports
(no API, no scraping): ChatGPT's `conversations.json` (a tree of message
nodes under `mapping`), and Claude's `conversations.json` (a flat
`chat_messages` list). We normalize either into Zenith conversations.
"""
from __future__ import annotations

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
            sender = m.get("sender")
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
    raise ValueError(
        "Unrecognized export format — expected a ChatGPT or Claude conversations.json."
    )


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
    Conversations/messages always create new rows (so importing twice just
    duplicates them, same as re-importing a ChatGPT export would); memories
    and personas dedupe via their own service-layer logic so re-running an
    import is safe."""
    from app.services import memory_service, persona_service

    conversations = 0
    messages = 0
    for conv in data.get("conversations") or []:
        if not isinstance(conv, dict):
            continue
        title = (conv.get("title") or "Imported chat")[:200]
        c = storage.create_conversation(title)
        id_map: dict[str, str] = {}
        for m in conv.get("messages") or []:
            if not isinstance(m, dict) or not m.get("role") or not m.get("content"):
                continue
            old_parent = m.get("parent_id")
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
    for p in data.get("personas") or []:
        if isinstance(p, dict) and p.get("name") and p.get("system_prompt"):
            persona_service.create_persona(p["name"], p["system_prompt"], icon=p.get("icon"))
            personas += 1

    return {"conversations": conversations, "messages": messages, "memories": memories, "personas": personas}


def import_conversations(parsed: list[dict]) -> dict:
    """Create Zenith conversations from normalized data. Messages are chained
    linearly (each is the previous one's child) to match the branching
    model's active-chain shape."""
    conversations = 0
    messages = 0
    for conv in parsed:
        title = (conv["title"] or "Imported chat")[:200]
        c = storage.create_conversation(title)
        prev_id = None
        for m in conv["messages"]:
            msg = storage.add_message(
                c["id"], m["role"], m["content"],
                parent_id=prev_id, created_at=m.get("created_at"),
            )
            prev_id = msg["id"]
            messages += 1
        conversations += 1
    return {"conversations": conversations, "messages": messages}
