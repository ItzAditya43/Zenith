"""Outbound webhooks — POST a small JSON payload to configured URLs when
a real backend event happens (see events.py for the list). Lets your own
scripts react to Zenith instead of polling its API.

Delivery contract (also in docs/API.md):
  * Body: {"event", "timestamp", "delivery_id", "schema_version", "data"}.
  * Headers: X-Zenith-Event, X-Zenith-Delivery (stable across retries, so
    receivers can de-duplicate), X-Zenith-Signature: "sha256=<hex>" — an
    HMAC-SHA256 of "<timestamp>.<raw body>" with the webhook's secret, and
    X-Zenith-Timestamp carrying that timestamp.
  * Up to 3 attempts with backoff for network errors and 5xx/429. A hook
    that fails 10 deliveries in a row is switched off (with the reason
    shown in Settings) instead of retrying forever.

Targets are checked before sending: only http(s), and never cloud
metadata / link-local addresses. Loopback and LAN are allowed on purpose —
the common receiver is a script on the same machine.

Fire-and-forget: a slow or dead endpoint never blocks or fails the thing
that triggered the event.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import socket
import time
import uuid
from urllib.parse import urlparse

import httpx

from app.core.logging import get_logger
from app.db import storage
from app.db.storage import _conn

log = get_logger(__name__)

SCHEMA_VERSION = 1
_TIMEOUT = 8.0
ATTEMPTS = 3
BACKOFF = (0.0, 2.0, 8.0)
DISABLE_AFTER = 10
_BLOCKED_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


class UnsafeTarget(ValueError):
    pass


def check_target(url: str) -> None:
    """Raise UnsafeTarget for URLs a webhook must never hit."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise UnsafeTarget("Webhook URLs must be http:// or https:// with a host.")
    host = u.hostname.lower()
    if host in _BLOCKED_HOSTS:
        raise UnsafeTarget("Cloud metadata endpoints can't be webhook targets.")
    try:
        infos = socket.getaddrinfo(host, None)
        addrs = {str(i[4][0]) for i in infos}
    except (socket.gaierror, UnicodeError):
        return  # unresolvable now — the send itself will fail and be logged
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise UnsafeTarget(f"{host} resolves to {ip}, which isn't allowed as a webhook target.")
        if ip.is_loopback or ip.is_private:
            continue
        if ip.is_reserved:
            raise UnsafeTarget(f"{host} resolves to {ip}, which isn't allowed as a webhook target.")


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _record(webhook_id: str | None, target: str, event: str, key: str, attempts: int, status: str,
            http_status: int | None, error: str | None, body: bytes) -> None:
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO webhook_deliveries (id, webhook_id, target, event, delivery_key, attempts, status,"
                " http_status, error, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), webhook_id, target, event, key, attempts, status, http_status,
                 (error or "")[:500] or None, body.decode()[:4000], time.time()),
            )
            conn.execute(
                "DELETE FROM webhook_deliveries WHERE id IN (SELECT id FROM webhook_deliveries"
                " ORDER BY created_at DESC LIMIT -1 OFFSET 500)"
            )
            if webhook_id:
                if status == "delivered":
                    conn.execute("UPDATE webhooks SET consecutive_failures = 0 WHERE id = ?", (webhook_id,))
                else:
                    conn.execute("UPDATE webhooks SET consecutive_failures = consecutive_failures + 1 WHERE id = ?",
                                 (webhook_id,))
                    r = conn.execute("SELECT consecutive_failures FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
                    if r and r["consecutive_failures"] >= DISABLE_AFTER:
                        conn.execute(
                            "UPDATE webhooks SET enabled = 0, disabled_reason = ? WHERE id = ?",
                            (f"Turned off after {DISABLE_AFTER} failed deliveries in a row. Last error: {error or http_status}",
                             webhook_id),
                        )
    except Exception as exc:  # noqa: BLE001 — logging a delivery must never break it
        log.debug("webhook.record_failed", error=str(exc))


async def deliver(url: str, event: str, data: dict, *, secret: str | None = None, webhook_id: str | None = None,
                  extra: dict | None = None, client: httpx.AsyncClient | None = None,
                  backoff: tuple[float, ...] = BACKOFF) -> dict:
    """Send one event to one URL with signing, retries and a delivery record."""
    key = str(uuid.uuid4())
    payload = {"event": event, "timestamp": time.time(), "delivery_id": key, "schema_version": SCHEMA_VERSION,
               "data": data, **(extra or {})}
    body = json.dumps(payload, default=str).encode()
    try:
        check_target(url)
    except UnsafeTarget as exc:
        _record(webhook_id, url, event, key, 0, "blocked", None, str(exc), body)
        return {"status": "blocked", "error": str(exc), "delivery_id": key}
    ts = str(int(time.time()))
    headers = {"Content-Type": "application/json", "User-Agent": "Zenith-Webhook/1", "X-Zenith-Event": event,
               "X-Zenith-Delivery": key, "X-Zenith-Timestamp": ts}
    if secret:
        headers["X-Zenith-Signature"] = sign(secret, ts, body)
    own = client is None
    c = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
    status, http_status, error, attempts = "failed", None, None, 0
    try:
        for attempt in range(ATTEMPTS):
            if attempt and backoff[min(attempt, len(backoff) - 1)]:
                await asyncio.sleep(backoff[min(attempt, len(backoff) - 1)])
            attempts = attempt + 1
            try:
                resp = await c.post(url, content=body, headers=headers)
                http_status = resp.status_code
                if resp.status_code < 300:
                    status, error = "delivered", None
                    break
                error = f"HTTP {resp.status_code}"
                if resp.status_code < 500 and resp.status_code != 429:
                    break  # a 4xx won't fix itself on retry
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        if own:
            await c.aclose()
    _record(webhook_id, url, event, key, attempts, status, http_status, error, body)
    if status != "delivered":
        log.warning("webhook.delivery_failed", url=url, event=event, error=error)
    return {"status": status, "http_status": http_status, "error": error, "attempts": attempts, "delivery_id": key}


async def dispatch(event_type: str, data: dict) -> None:
    hooks = [h for h in storage.list_webhooks(enabled_only=True) if event_type in h["event_types"]]
    for hook in hooks:
        try:
            await deliver(hook["url"], event_type, data, secret=storage.webhook_secret(hook["id"]), webhook_id=hook["id"])
        except Exception as exc:  # noqa: BLE001
            log.warning("webhook.dispatch_failed", url=hook["url"], event=event_type, error=str(exc))


def deliveries(webhook_id: str | None = None, limit: int = 50) -> list[dict]:
    with _conn() as conn:
        if webhook_id:
            rows = conn.execute("SELECT * FROM webhook_deliveries WHERE webhook_id = ? ORDER BY created_at DESC LIMIT ?",
                                (webhook_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM webhook_deliveries ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
