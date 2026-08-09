"""Outbound webhooks — POST a small JSON payload to configured URLs when
a real backend event happens (see events.py for the list). Lets your own
scripts on the same machine react to Zenith instead of polling its API.

Fire-and-forget: a slow or dead endpoint must never block or fail the
thing that triggered the event (a schedule run finishing, a digest being
generated, ...). Each webhook gets its own short timeout and any error
is logged, not raised.
"""
from __future__ import annotations

import time

import httpx

from app.core.logging import get_logger
from app.db import storage

log = get_logger(__name__)

_TIMEOUT = 8.0


async def dispatch(event_type: str, data: dict) -> None:
    hooks = [h for h in storage.list_webhooks(enabled_only=True) if event_type in h["event_types"]]
    if not hooks:
        return
    payload = {"event": event_type, "timestamp": time.time(), "data": data}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for hook in hooks:
            try:
                resp = await client.post(hook["url"], json=payload)
                if resp.status_code >= 400:
                    log.warning("webhook.non_2xx", url=hook["url"], status=resp.status_code)
            except Exception as exc:
                log.warning("webhook.dispatch_failed", url=hook["url"], event=event_type, error=str(exc))
