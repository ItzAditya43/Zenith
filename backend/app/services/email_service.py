"""Personal email client: read your inbox over IMAP, send/reply over SMTP,
using your own mail account — no third-party mail API, same "your data,
your machine" model as the rest of Zenith. Uses only the stdlib
(imaplib/smtplib/email), so no new dependency.

AI summarize/auto-reply reuse the same local Ollama model the rest of the
app uses — a draft reply is always shown for review before it's sent;
nothing goes out automatically.
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class EmailError(Exception):
    pass


def _require_configured() -> None:
    if not settings.get("email_enabled"):
        raise EmailError("Email isn't configured. Set it up in Settings → Email.")
    for key in ("email_imap_host", "email_smtp_host", "email_username", "email_password"):
        if not settings.get(key):
            raise EmailError(f"Missing email config: {key}. Finish setup in Settings → Email.")


def _decode(raw: str | None) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return " ".join(out)


def _payload_bytes(part: email.message.Message) -> bytes:
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, bytes) else b""


def _fetched_bytes(msg_data) -> bytes:
    """imaplib's fetch() result is [(b'1 (RFC822 {n}', b'<raw message>'), b')']."""
    first = msg_data[0]
    raw = first[1] if isinstance(first, tuple) else first
    return raw if isinstance(raw, bytes) else b""


def _extract_body(msg: email.message.Message, max_chars: int = 4000) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                try:
                    body = _payload_bytes(part).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    return body[:max_chars]
                except Exception:
                    continue
        return ""
    try:
        body = _payload_bytes(msg).decode(msg.get_content_charset() or "utf-8", errors="replace")
        return body[:max_chars]
    except Exception:
        return ""


def test_connection() -> dict:
    """Round-trips a login to both IMAP and SMTP without sending/reading
    anything, so Settings can show "connected" instead of failing silently
    on the first real fetch."""
    _require_configured()
    host = settings.get("email_imap_host")
    port = int(settings.get("email_imap_port", 993))
    user = settings.get("email_username")
    pw = settings.get("email_password")
    try:
        with imaplib.IMAP4_SSL(host, port, timeout=10) as imap:
            imap.login(user, pw)
    except Exception as exc:
        raise EmailError(f"IMAP login failed: {exc}") from exc
    smtp_host = settings.get("email_smtp_host")
    smtp_port = int(settings.get("email_smtp_port", 587))
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(user, pw)
    except Exception as exc:
        raise EmailError(f"SMTP login failed: {exc}") from exc
    return {"ok": True}


def list_messages(folder: str = "INBOX", limit: int | None = None) -> list[dict]:
    _require_configured()
    host = settings.get("email_imap_host")
    port = int(settings.get("email_imap_port", 993))
    user = settings.get("email_username")
    pw = settings.get("email_password")
    limit = limit or int(settings.get("email_fetch_count", 20))

    try:
        with imaplib.IMAP4_SSL(host, port, timeout=15) as imap:
            imap.login(user, pw)
            imap.select(folder, readonly=True)
            status, data = imap.search(None, "ALL")
            if status != "OK":
                return []
            ids = data[0].split()
            ids = ids[-limit:][::-1]  # most recent first
            out = []
            for mid in ids:
                status, msg_data = imap.fetch(mid, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(_fetched_bytes(msg_data))
                date = None
                try:
                    date = parsedate_to_datetime(str(msg.get("Date") or "")).timestamp()
                except Exception:
                    pass
                out.append({
                    "id": mid.decode(),
                    "subject": _decode(msg.get("Subject")),
                    "from": _decode(msg.get("From")),
                    "date": date,
                    "snippet": _extract_body(msg, 300).strip().replace("\n", " ")[:200],
                })
            return out
    except (imaplib.IMAP4.error, OSError) as exc:
        raise EmailError(f"IMAP error: {exc}") from exc


def get_message(message_id: str, folder: str = "INBOX") -> dict:
    _require_configured()
    host = settings.get("email_imap_host")
    port = int(settings.get("email_imap_port", 993))
    user = settings.get("email_username")
    pw = settings.get("email_password")
    try:
        with imaplib.IMAP4_SSL(host, port, timeout=15) as imap:
            imap.login(user, pw)
            imap.select(folder, readonly=True)
            status, msg_data = imap.fetch(message_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                raise EmailError("Message not found.")
            msg = email.message_from_bytes(_fetched_bytes(msg_data))
            return {
                "id": message_id,
                "subject": _decode(msg.get("Subject")),
                "from": _decode(msg.get("From")),
                "to": _decode(msg.get("To")),
                "body": _extract_body(msg, 8000),
            }
    except (imaplib.IMAP4.error, OSError) as exc:
        raise EmailError(f"IMAP error: {exc}") from exc


async def summarize(message_id: str, folder: str = "INBOX") -> str:
    from app.services.ollama_client import OllamaClient
    from app.services.router import ModelRegistry, ModelRouter

    msg = get_message(message_id, folder)
    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    model = router._match_capability("small_fast", installed) or (installed[0] if installed else None)  # noqa: SLF001
    if not model:
        raise EmailError("No local model available to summarize with.")
    prompt = (
        "Summarize this email in 2-3 short sentences — what it's about and "
        "whether it needs a response.\n\n"
        f"From: {msg['from']}\nSubject: {msg['subject']}\n\n{msg['body']}"
    )
    return await OllamaClient().chat(model, [{"role": "user", "content": prompt}])


async def _research_query_for(msg: dict) -> str | None:
    """Asks the model whether this looks like a routine inquiry worth a
    quick web search before drafting (e.g. "what's your return policy",
    "when does X ship") — vs. something personal/contextual where a web
    search would be noise. Returns a search query, or None."""
    from app.services.ollama_client import OllamaClient
    from app.services.router import ModelRegistry, ModelRouter

    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    model = router._match_capability("small_fast", installed) or (installed[0] if installed else None)  # noqa: SLF001
    if not model:
        return None
    prompt = (
        "Does answering this email require looking up a factual/current-events "
        "answer (e.g. a product spec, a policy, an address, a public fact)? If "
        "yes, respond with ONLY a short web search query. If no (it's personal, "
        "opinion-based, or answerable from context alone), respond with exactly: NONE\n\n"
        f"Subject: {msg['subject']}\n\n{msg['body'][:1000]}"
    )
    out = (await OllamaClient().chat(model, [{"role": "user", "content": prompt}])).strip()
    if not out or out.upper().startswith("NONE"):
        return None
    return out.strip('"')


async def draft_reply(message_id: str, instruction: str = "", folder: str = "INBOX", auto_research: bool = True) -> dict:
    """Returns {"draft": str, "research_query": str | None, "research_sources": [...]}
    — a reply drafted directly from the email, optionally informed by a quick
    web search when the message looks like a routine factual inquiry. The
    draft is always returned for review; nothing here sends anything."""
    from app.services.ollama_client import OllamaClient
    from app.services.router import ModelRegistry, ModelRouter

    msg = get_message(message_id, folder)
    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    model = router._match_capability("general", installed) or (installed[0] if installed else None)  # noqa: SLF001
    if not model:
        raise EmailError("No local model available to draft with.")

    research_query = None
    research_block = ""
    sources: list[dict] = []
    if auto_research and not instruction:
        try:
            research_query = await _research_query_for(msg)
            if research_query:
                from app.services import web_service
                results = await web_service.search(research_query)
                sources = results[:3]
                if sources:
                    research_block = "\n\nRelevant information found via web search:\n" + "\n".join(
                        f"- {r.get('title', '')}: {r.get('snippet', '')}" for r in sources
                    )
        except Exception as exc:
            log.warning("email.auto_research_failed", error=str(exc))

    prompt = (
        "Draft a reply to this email. Be concise and professional. "
        + (f"Additional instruction: {instruction}\n\n" if instruction else "\n")
        + f"Original from: {msg['from']}\nSubject: {msg['subject']}\n\n{msg['body']}"
        + research_block
        + "\n\nReturn ONLY the reply body text, no subject line, no signature placeholder."
    )
    draft = await OllamaClient().chat(model, [{"role": "user", "content": prompt}])
    return {"draft": draft, "research_query": research_query, "research_sources": sources}


def send_message(to: str, subject: str, body: str, in_reply_to: str | None = None) -> None:
    _require_configured()
    user = settings.get("email_username")
    pw = settings.get("email_password")
    smtp_host = settings.get("email_smtp_host")
    smtp_port = int(settings.get("email_smtp_port", 587))

    mime = MIMEText(body)
    mime["From"] = user
    mime["To"] = to
    mime["Subject"] = subject if not in_reply_to else f"Re: {subject}"

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(user, pw)
            smtp.sendmail(user, [to], mime.as_string())
    except Exception as exc:
        raise EmailError(f"Send failed: {exc}") from exc


# ---- triage, filters and drafts ---------------------------------------------------

CATEGORIES = ("urgent", "reply", "fyi", "newsletter")
FILTER_FIELDS = ("from", "subject", "body")


def list_filters() -> list[dict]:
    from app.db.storage import _conn

    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM email_filters ORDER BY created_at ASC")]


def add_filter(name: str, field: str, contains: str, category: str) -> dict:
    import time
    import uuid

    from app.db.storage import _conn

    if field not in FILTER_FIELDS:
        raise EmailError(f"field must be one of {FILTER_FIELDS}")
    if category not in CATEGORIES:
        raise EmailError(f"category must be one of {CATEGORIES}")
    if not contains.strip():
        raise EmailError("Say what the filter should look for.")
    fid = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute("INSERT INTO email_filters (id, name, field, contains, category, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (fid, name.strip() or contains.strip(), field, contains.strip(), category, time.time()))
    return {"id": fid, "name": name.strip() or contains.strip(), "field": field, "contains": contains.strip(), "category": category}


def delete_filter(fid: str) -> None:
    from app.db.storage import _conn

    with _conn() as conn:
        conn.execute("DELETE FROM email_filters WHERE id = ?", (fid,))


def match_filter(msg: dict, filters: list[dict] | None = None) -> dict | None:
    for f in filters if filters is not None else list_filters():
        hay = str(msg.get("snippet" if f["field"] == "body" else f["field"]) or "").lower()
        if f["contains"].lower() in hay:
            return f
    return None


def _flag(message_id: str) -> dict | None:
    from app.db.storage import _conn

    with _conn() as conn:
        r = conn.execute("SELECT * FROM email_flags WHERE message_id = ?", (message_id,)).fetchone()
    return dict(r) if r else None


def _record(m: dict, category: str, reason: str) -> None:
    import time

    from app.db.storage import _conn

    with _conn() as conn:
        conn.execute(
            """INSERT INTO email_flags (message_id, subject, sender, reason, urgent, seen, flagged_at, category)
               VALUES (?, ?, ?, ?, ?, 0, ?, ?)
               ON CONFLICT(message_id) DO UPDATE SET category = excluded.category, reason = excluded.reason,
                 urgent = excluded.urgent""",
            (m["id"], m["subject"], m["from"], reason, 1 if category == "urgent" else 0, time.time(), category),
        )


async def triage(limit: int = 15, force: bool = False) -> dict:
    """Sort recent mail into urgent / reply / fyi / newsletter. Your filters
    decide first (no model call); the model handles the rest, once per
    message. Urgent ones raise the `urgent_email` event as before."""
    from app.services.ollama_client import OllamaClient
    from app.services.router import ModelRegistry, ModelRouter

    if not settings.get("email_enabled"):
        return {"triaged": 0, "urgent": 0}
    try:
        messages = await asyncio.to_thread(list_messages, "INBOX", limit)
    except EmailError as exc:
        log.warning("email.triage_fetch_failed", error=str(exc))
        return {"triaged": 0, "urgent": 0, "error": str(exc)}
    todo = [m for m in messages if force or not _flag(m["id"])]
    if not todo:
        return {"triaged": 0, "urgent": 0}
    filters = list_filters()
    model = None
    triaged = urgent = 0
    for m in todo:
        f = match_filter(m, filters)
        if f:
            category, reason = f["category"], f"filter: {f['name']}"
        else:
            if model is None:
                registry = ModelRegistry()
                installed = await registry.models()
                model = ModelRouter(registry=registry)._match_capability("small_fast", installed) or (installed[0] if installed else "")  # noqa: SLF001
            if not model:
                break
            prompt = (
                "Sort this email into exactly one category and reply with one line, 'CATEGORY: short reason'.\n"
                "URGENT = time-sensitive: a deadline, something to sign, a legal/financial/business action.\n"
                "REPLY = a person is asking you something or expects an answer.\n"
                "NEWSLETTER = marketing, newsletters, promotions, automated digests.\n"
                "FYI = everything else worth knowing but needing no action.\n\n"
                f"From: {m['from']}\nSubject: {m['subject']}\n\n{m['snippet']}"
            )
            try:
                out = (await OllamaClient().chat(model, [{"role": "user", "content": prompt}])).strip()
            except Exception as exc:
                log.warning("email.triage_classify_failed", error=str(exc))
                continue
            head, _, rest = out.partition(":")
            word = head.strip().strip("*").upper()
            category = {"URGENT": "urgent", "REPLY": "reply", "NEWSLETTER": "newsletter", "FYI": "fyi"}.get(word)
            if not category:
                category = "urgent" if "URGENT" in out.upper()[:20] else "fyi"
            reason = rest.strip()[:300]
        _record(m, category, reason)
        triaged += 1
        if category == "urgent":
            urgent += 1
            try:
                from app.services import events
                await events.emit("urgent_email", {"subject": m["subject"], "from": m["from"], "reason": reason})
            except Exception as exc:
                log.debug("email.event_emit_failed", error=str(exc))
    return {"triaged": triaged, "urgent": urgent}


async def scan_for_urgent(limit: int = 10) -> int:
    """Background timer entry point (main.py): triage new mail and return
    how many urgent messages it found. Never raises."""
    try:
        return (await triage(limit))["urgent"]
    except Exception as exc:  # noqa: BLE001
        log.warning("email.triage_failed", error=str(exc))
        return 0


def inbox(limit: int | None = None) -> list[dict]:
    """Recent messages with their triage category and whether a draft
    reply is waiting."""
    from app.db.storage import _conn

    msgs = list_messages("INBOX", limit)
    with _conn() as conn:
        flags = {r["message_id"]: dict(r) for r in conn.execute("SELECT * FROM email_flags")}
        drafts = {r["message_id"] for r in conn.execute("SELECT message_id FROM email_drafts WHERE status = 'draft'")}
    for m in msgs:
        f = flags.get(m["id"])
        m["category"] = (f or {}).get("category")
        m["reason"] = (f or {}).get("reason")
        m["has_draft"] = m["id"] in drafts
    return msgs


def _sender_addr(raw: str) -> str:
    from email.utils import parseaddr

    return parseaddr(raw or "")[1] or raw


def list_drafts(status: str = "draft") -> list[dict]:
    from app.db.storage import _conn

    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM email_drafts WHERE status = ? ORDER BY updated_at DESC", (status,))]


def get_draft(did: str) -> dict | None:
    from app.db.storage import _conn

    with _conn() as conn:
        r = conn.execute("SELECT * FROM email_drafts WHERE id = ?", (did,)).fetchone()
    return dict(r) if r else None


async def create_draft(message_id: str, instruction: str = "") -> dict:
    """Draft a reply with the model and save it for review. Never sends."""
    import time
    import uuid

    from app.db.storage import _conn

    msg = await asyncio.to_thread(get_message, message_id, "INBOX")
    result = await draft_reply(message_id, instruction, "INBOX", auto_research=not instruction)
    subject = msg["subject"] if msg["subject"].lower().startswith("re:") else f"Re: {msg['subject']}"
    did, now = uuid.uuid4().hex[:12], time.time()
    with _conn() as conn:
        conn.execute("UPDATE email_drafts SET status = 'replaced', updated_at = ? WHERE message_id = ? AND status = 'draft'", (now, message_id))
        conn.execute(
            "INSERT INTO email_drafts (id, message_id, to_addr, subject, body, original_from, original_subject, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
            (did, message_id, _sender_addr(msg["from"]), subject, result["draft"].strip(), msg["from"], msg["subject"], now, now),
        )
    return {**get_draft(did), "research_query": result.get("research_query"), "research_sources": result.get("research_sources")}  # type: ignore[arg-type]


def update_draft(did: str, to: str | None = None, subject: str | None = None, body: str | None = None) -> dict:
    import time

    from app.db.storage import _conn

    d = get_draft(did)
    if not d or d["status"] != "draft":
        raise EmailError("That draft isn't open any more.")
    with _conn() as conn:
        conn.execute("UPDATE email_drafts SET to_addr = ?, subject = ?, body = ?, updated_at = ? WHERE id = ?",
                     (to if to is not None else d["to_addr"], subject if subject is not None else d["subject"],
                      body if body is not None else d["body"], time.time(), did))
    return get_draft(did)  # type: ignore[return-value]


def discard_draft(did: str) -> None:
    import time

    from app.db.storage import _conn

    with _conn() as conn:
        conn.execute("UPDATE email_drafts SET status = 'discarded', updated_at = ? WHERE id = ? AND status = 'draft'", (time.time(), did))


def send_draft(did: str) -> dict:
    """Send a reviewed draft. The only way a drafted reply leaves the machine."""
    import time

    from app.db.storage import _conn

    d = get_draft(did)
    if not d or d["status"] != "draft":
        raise EmailError("That draft isn't open any more.")
    if not d["to_addr"].strip() or not d["body"].strip():
        raise EmailError("The draft needs a recipient and some text.")
    send_message(d["to_addr"], d["subject"], d["body"])
    with _conn() as conn:
        conn.execute("UPDATE email_drafts SET status = 'sent', sent_at = ?, updated_at = ? WHERE id = ?", (time.time(), time.time(), did))
    return get_draft(did)  # type: ignore[return-value]
