"""Internal event bus — one `emit()` call site per real thing that
happens (a digest was generated, a schedule finished, an urgent email
showed up, memories were found to conflict, a watched folder got new
files), fanning out to whichever webhooks and automation rules are
subscribed. Keeps "what events exist" defined in exactly one place
instead of duplicated across webhook and rule-matching logic.

Best-effort throughout — a broken webhook URL or a bad rule action must
never take down the thing that triggered the event (a schedule run, a
folder scan, ...).
"""
from __future__ import annotations

from app.core.logging import get_logger

log = get_logger(__name__)

EVENT_TYPES = [
    "digest_generated",
    "schedule_completed",
    "urgent_email",
    "memory_conflict_found",
    "folder_file_added",
]


async def emit(event_type: str, data: dict) -> None:
    if event_type not in EVENT_TYPES:
        log.warning("events.unknown_type", event_type=event_type)
        return
    try:
        from app.services import webhook_service
        await webhook_service.dispatch(event_type, data)
    except Exception as exc:
        log.warning("events.webhook_dispatch_failed", event_type=event_type, error=str(exc))
    try:
        from app.services import automation_service
        await automation_service.handle_event(event_type, data)
    except Exception as exc:
        log.warning("events.automation_dispatch_failed", event_type=event_type, error=str(exc))
    try:
        from app.services import notify_service
        await notify_service.dispatch(event_type, data)
    except Exception as exc:
        log.warning("events.notify_dispatch_failed", event_type=event_type, error=str(exc))
