"""Safe sharing: preview what's sensitive, redact it, share a snapshot.

A share link used to expose the live conversation. Now sharing makes a
redacted *snapshot*: the user sees what was detected (emails, phone
numbers, keys and tokens, IP addresses, home-folder paths) plus any text
they add, picks which messages to include, and the link (or the
downloaded Markdown) contains only that. Attachments are listed by name
only, and only when the user opts in. Detection is a helper, not a
guarantee — the preview shows the exact text that will be shared.
"""
from __future__ import annotations

import json
import re
import time
import uuid

from app.db.storage import _conn

PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("key", "Key or token", re.compile(
        r"\b(?:sk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abpr]-[A-Za-z0-9-]{10,}"
        r"|AIza[0-9A-Za-z_-]{30,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")),
    ("email", "Email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("phone", "Phone number", re.compile(r"(?<![\w.])\+?\d[\d ()-]{8,}\d(?![\w.])")),
    ("ip", "IP address", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
    ("path", "Home-folder path", re.compile(r"(?:/home/|/Users/|C:\\\\Users\\\\)[^\s/\\\\:'\"`]+")),
]
LABEL = {k: f"[{label.lower()}]" for k, label, _ in PATTERNS}


def _messages(conversation_id: str) -> list[dict]:
    from app.db import storage

    return [m for m in storage.get_messages(conversation_id) if m.get("role") in ("user", "assistant")]


def find_sensitive(text: str) -> list[tuple[str, str]]:
    out, taken = [], []
    for kind, _label, rx in PATTERNS:
        for m in rx.finditer(text or ""):
            span = m.span()
            if any(s < span[1] and span[0] < e for s, e in taken):
                continue  # already covered by an earlier, more specific match
            taken.append(span)
            out.append((kind, m.group(0)))
    return out


def preview(conversation_id: str) -> dict:
    msgs = _messages(conversation_id)
    found: dict[tuple[str, str], dict] = {}
    for m in msgs:
        for kind, text in find_sensitive(m.get("content") or ""):
            f = found.setdefault((kind, text), {"kind": kind, "text": text, "count": 0, "message_ids": []})
            f["count"] += 1
            if m["id"] not in f["message_ids"]:
                f["message_ids"].append(m["id"])
    labels = {k: label for k, label, _ in PATTERNS}
    findings = sorted(found.values(), key=lambda f: (list(labels).index(f["kind"]), f["text"]))
    for f in findings:
        f["label"] = labels[f["kind"]]
    return {
        "messages": [{"id": m["id"], "role": m["role"], "content": m["content"], "model": m.get("model"),
                      "attachments": [a.get("filename") for a in (m.get("attachments") or []) if isinstance(a, dict)]}
                     for m in msgs],
        "findings": findings,
    }


def _redact(text: str, redact: list[dict]) -> str:
    for r in sorted(redact, key=lambda r: -len(r["text"])):
        if r["text"]:
            text = text.replace(r["text"], r.get("replacement") or LABEL.get(r.get("kind", ""), "[redacted]"))
    return text


def build(conversation_id: str, redact: list[dict], exclude_ids: list[str], include_attachments: bool) -> dict:
    from app.db import storage

    conv = storage.get_conversation(conversation_id)
    if not conv:
        raise LookupError("No such conversation.")
    redact = [r for r in redact if isinstance(r, dict) and str(r.get("text") or "").strip()]
    out = []
    for m in _messages(conversation_id):
        if m["id"] in exclude_ids:
            continue
        item = {"role": m["role"], "content": _redact(m.get("content") or "", redact), "model": m.get("model"),
                "created_at": m.get("created_at")}
        if include_attachments:
            names = [a.get("filename") for a in (m.get("attachments") or []) if isinstance(a, dict) and a.get("filename")]
            if names:
                item["attachments"] = [_redact(n, redact) for n in names]
        out.append(item)
    return {"title": _redact(conv["title"], redact), "messages": out}


def create_snapshot(conversation_id: str, redact: list[dict], exclude_ids: list[str], include_attachments: bool) -> str:
    snap = build(conversation_id, redact, exclude_ids, include_attachments)
    if not snap["messages"]:
        raise ValueError("Pick at least one message to share.")
    token = uuid.uuid4().hex
    with _conn() as conn:
        conn.execute("DELETE FROM share_snapshots WHERE conversation_id = ?", (conversation_id,))
        conn.execute("INSERT INTO share_snapshots (token, conversation_id, title, messages, created_at) VALUES (?, ?, ?, ?, ?)",
                     (token, conversation_id, snap["title"], json.dumps(snap["messages"]), time.time()))
        conn.execute("UPDATE conversations SET share_token = ? WHERE id = ?", (token, conversation_id))
    return token


def get_snapshot(token: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM share_snapshots WHERE token = ?", (token,)).fetchone()
    if not r:
        return None
    return {"title": r["title"], "created_at": r["created_at"], "messages": json.loads(r["messages"])}


def revoke(conversation_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM share_snapshots WHERE conversation_id = ?", (conversation_id,))


def to_markdown(snap: dict) -> str:
    lines = [f"# {snap['title']}", ""]
    for m in snap["messages"]:
        model = f" ({m['model']})" if m.get("model") else ""
        who = "You" if m["role"] == "user" else f"Assistant{model}"
        lines += [f"**{who}:**", "", m["content"], ""]
        if m.get("attachments"):
            lines += ["_Attachments: " + ", ".join(m["attachments"]) + "_", ""]
    return "\n".join(lines).rstrip() + "\n"
