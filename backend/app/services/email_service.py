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


def _extract_body(msg: email.message.Message, max_chars: int = 4000) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    return body[:max_chars]
                except Exception:
                    continue
        return ""
    try:
        body = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
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
                msg = email.message_from_bytes(msg_data[0][1])
                date = None
                try:
                    date = parsedate_to_datetime(msg.get("Date")).timestamp()
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
            status, msg_data = imap.fetch(message_id.encode(), "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                raise EmailError("Message not found.")
            msg = email.message_from_bytes(msg_data[0][1])
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


async def scan_for_urgent(limit: int = 10) -> int:
    """Background triage: looks at the most recent messages, classifies
    any not already seen, and records the urgent ones. Returns how many
    new urgent flags were found this pass. Called on a timer from
    main.py, same pattern as the folder scanner / schedule runner —
    never raises, a flaky inbox connection just means "nothing new this
    cycle" rather than crashing the loop."""
    from app.db import storage
    from app.services.ollama_client import OllamaClient
    from app.services.router import ModelRegistry, ModelRouter

    if not settings.get("email_enabled"):
        return 0
    try:
        messages = await asyncio.to_thread(list_messages, "INBOX", limit)
    except EmailError as exc:
        log.warning("email.triage_fetch_failed", error=str(exc))
        return 0

    unseen = [m for m in messages if not storage.is_email_flagged_seen(m["id"])]
    if not unseen:
        return 0

    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    model = router._match_capability("small_fast", installed) or (installed[0] if installed else None)  # noqa: SLF001
    if not model:
        return 0

    client = OllamaClient()
    new_urgent = 0
    for m in unseen:
        prompt = (
            "Is this email urgent — a time-sensitive deadline, a document needing a "
            "signature, a legal/financial/business action item? Reply with exactly "
            "one line: either 'URGENT: <one-sentence reason>' or 'NOT_URGENT'.\n\n"
            f"From: {m['from']}\nSubject: {m['subject']}\n\n{m['snippet']}"
        )
        try:
            out = (await client.chat(model, [{"role": "user", "content": prompt}])).strip()
        except Exception as exc:
            log.warning("email.triage_classify_failed", error=str(exc))
            continue
        urgent = out.upper().startswith("URGENT")
        reason = out.split(":", 1)[1].strip() if urgent and ":" in out else ""
        storage.record_email_flag(m["id"], m["subject"], m["from"], reason, urgent)
        if urgent:
            new_urgent += 1
    return new_urgent
