"""Personal email client: read your inbox over IMAP, send/reply over SMTP,
using your own mail account — no third-party mail API, same "your data,
your machine" model as the rest of Cortex. Uses only the stdlib
(imaplib/smtplib/email), so no new dependency.

AI summarize/auto-reply reuse the same local Ollama model the rest of the
app uses — a draft reply is always shown for review before it's sent;
nothing goes out automatically.
"""
from __future__ import annotations

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


async def draft_reply(message_id: str, instruction: str = "", folder: str = "INBOX") -> str:
    from app.services.ollama_client import OllamaClient
    from app.services.router import ModelRegistry, ModelRouter

    msg = get_message(message_id, folder)
    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    model = router._match_capability("general", installed) or (installed[0] if installed else None)  # noqa: SLF001
    if not model:
        raise EmailError("No local model available to draft with.")
    prompt = (
        "Draft a reply to this email. Be concise and professional. "
        + (f"Additional instruction: {instruction}\n\n" if instruction else "\n")
        + f"Original from: {msg['from']}\nSubject: {msg['subject']}\n\n{msg['body']}\n\n"
        "Return ONLY the reply body text, no subject line, no signature placeholder."
    )
    return await OllamaClient().chat(model, [{"role": "user", "content": prompt}])


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
