"""Push notifications via ntfy.sh — a free, keyless, self-hostable push
service. Lets schedule completions / urgent emails / digest generation
reach you away from the machine, not just via desktop notification
(which only works while the app is open).

Off by default: unlike webhooks (your own LAN scripts), this leaves your
machine to a third-party relay by design, so it requires explicit opt-in
(`notify_ntfy_enabled`), a configured topic, and the event type to be in
the user's allow-list — same "free by construction, no paid APIs, opt-in
for anything that leaves the machine" posture as web search / Ollama
Cloud.

Fire-and-forget, same pattern as webhook_service.py: a slow or dead
endpoint must never block or fail the thing that triggered the event.
Any error is logged, not raised.
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 8.0


def _format_message(event_type: str, data: dict) -> tuple[str, str]:
    """Return (title, body) for a given event. Keep it short and
    human-readable — ntfy notifications are read on a phone lock screen."""
    if event_type == "digest_generated":
        title = "Zenith: daily digest ready"
        body = data.get("summary") or data.get("title") or "Your daily digest has been generated."
    elif event_type == "schedule_completed":
        name = data.get("name") or data.get("schedule_name") or data.get("id") or "a schedule"
        title = "Zenith: schedule completed"
        body = data.get("result") or data.get("summary") or f"'{name}' finished running."
    elif event_type == "urgent_email":
        sender = data.get("from") or data.get("sender") or "someone"
        subject = data.get("subject") or "(no subject)"
        title = "Zenith: urgent email"
        body = f"From {sender}: {subject}"
    elif event_type == "memory_conflict_found":
        title = "Zenith: memory conflict found"
        body = data.get("summary") or data.get("content") or "A conflicting memory was detected."
    elif event_type == "folder_file_added":
        folder = data.get("folder") or data.get("path") or "a watched folder"
        fname = data.get("filename") or data.get("file") or ""
        title = "Zenith: new file detected"
        body = f"{fname} added to {folder}" if fname else f"New file added to {folder}"
    else:
        title = f"Zenith: {event_type}"
        body = str(data) if data else event_type
    return title, body


async def dispatch(event_type: str, data: dict) -> None:
    if not settings.get("notify_ntfy_enabled", False):
        return
    topic = settings.get("notify_ntfy_topic", "") or ""
    if not topic:
        return
    event_types = settings.get("notify_event_types", []) or []
    if event_type not in event_types:
        return

    base_url = (settings.get("notify_ntfy_url", "") or "https://ntfy.sh").rstrip("/")
    url = f"{base_url}/{topic}"
    title, body = _format_message(event_type, data or {})

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                content=body.encode("utf-8"),
                headers={"Title": title},
            )
            if resp.status_code >= 400:
                log.warning("notify.non_2xx", url=url, status=resp.status_code)
    except Exception as exc:
        log.warning("notify.dispatch_failed", url=url, event=event_type, error=str(exc))
