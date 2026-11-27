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

import asyncio

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 8.0


def _format_message(event_type: str, data: dict) -> tuple[str, str]:
    """Return (title, body) for a given event. Keep it short and
    human-readable — ntfy notifications are read on a phone lock screen."""
    if event_type == "test":
        title = "Zenith: test notification"
        body = data.get("result") or "Notifications are working."
    elif event_type == "schedule_failing":
        title = "Zenith: a schedule keeps failing"
        body = data.get("result") or f"'{data.get('name', 'A schedule')}' failed several times in a row."
    elif event_type == "digest_generated":
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
    elif event_type == "todo_created":
        title = "Zenith: to-do added"
        body = data.get("text") or "A to-do was added."
    elif event_type == "todo_completed":
        title = "Zenith: to-do done"
        body = data.get("text") or "A to-do was completed."
    elif event_type == "agent_run_finished":
        title = f"Zenith: task {data.get('status') or 'finished'}"
        body = data.get("summary") or data.get("prompt") or "A background task finished."
    elif event_type == "agent_run_needs_approval":
        title = "Zenith: a task needs your OK"
        body = data.get("detail") or data.get("prompt") or "A background task is waiting for approval."
    else:
        title = f"Zenith: {event_type}"
        body = str(data) if data else event_type
    return title, body


def _redacted(event_type: str, title: str, body: str) -> tuple[str, str]:
    """Unless the user opted in, the push carries no private text — just
    which kind of thing happened."""
    if settings.get("notify_ntfy_include_content", False):
        return title, body
    return title, "Open Zenith to see the details."


async def send(event_type: str, data: dict, *, force: bool = False) -> dict:
    """Push one notification to ntfy. Returns {status, error?}. `force`
    skips the per-event opt-in and quiet hours (used by the test button)."""
    if not settings.get("notify_ntfy_enabled", False) and not force:
        return {"status": "off"}
    topic = settings.get("notify_ntfy_topic", "") or ""
    if not topic:
        return {"status": "off", "error": "No ntfy topic set."}
    if not force:
        if event_type not in (settings.get("notify_event_types", []) or []):
            return {"status": "not_selected"}
        from app.services.notification_service import in_quiet_hours
        if in_quiet_hours():
            log.info("notify.quiet_hours", event_type=event_type)
            return {"status": "quiet_hours"}

    base_url = (settings.get("notify_ntfy_url", "") or "https://ntfy.sh").rstrip("/")
    url = f"{base_url}/{topic}"
    title, body = _redacted(event_type, *_format_message(event_type, data or {}))
    last_err = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, content=body.encode("utf-8"), headers={"Title": title})
            if resp.status_code < 400:
                return {"status": "sent"}
            last_err = f"HTTP {resp.status_code}"
            if resp.status_code < 500:
                break
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"[:200]
        if attempt == 0:
            await asyncio.sleep(1.5)
    log.warning("notify.dispatch_failed", url=base_url, event=event_type, error=last_err)
    return {"status": "failed", "error": last_err}


async def dispatch(event_type: str, data: dict) -> None:
    res = await send(event_type, data)
    if res["status"] in ("sent", "failed"):
        try:
            from app.services.notification_service import set_push_status
            set_push_status(event_type, res["status"], res.get("error"))
        except Exception as exc:  # noqa: BLE001
            log.debug("notify.status_record_failed", error=str(exc))
