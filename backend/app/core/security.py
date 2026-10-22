"""Network-exposure guard, config redaction, and passcode brute-force limits.

Zenith is single-user and assumes "the person at this machine" is trusted.
Before this module that assumption was enforced only by CORS, which a
non-browser client (curl on the same Wi-Fi) simply ignores — and agent mode
can run shell commands. The rules now enforced on every /api/* request:

1. **Local clients** (loopback, plus ZENITH_TRUSTED_NETWORKS — see below)
   keep working with zero setup, exactly as before.
2. **Remote clients** (anything else: a phone on the LAN, a Tailscale peer)
   are refused with 403 unless a gate is configured — a passcode lock or
   shared-secret auth. Once one is, the request falls through to that gate.
3. **DNS rebinding**: a local client's Host header must be localhost, a
   literal IP, or listed in ZENITH_ALLOWED_HOSTS / `allowed_hosts`. A
   malicious page whose domain resolves to 127.0.0.1 sends its own
   hostname as Host and is rejected, so it can't drive the API from your
   browser.

ZENITH_TRUSTED_NETWORKS (comma-separated CIDRs/hosts) exists for Docker:
a browser on the host reaching a published port arrives from the bridge
gateway, not 127.0.0.1. It is only honoured while ZENITH_HOST_BIND (the
address docker-compose publishes the port on) is loopback — once you
publish on 0.0.0.0 for LAN access, the gateway may also front LAN
traffic (Docker Desktop), so it is treated as remote like everything else.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import threading
import time
from functools import lru_cache
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

# Config keys never sent to a client. Secrets come back as REDACTED (so the
# UI can show "set" without seeing the value) and REDACTED in a PATCH means
# "unchanged". lock_pass_hash is dropped entirely.
SECRET_KEYS = ("email_password", "auth_shared_secret")
HIDDEN_KEYS = ("lock_pass_hash",)
REDACTED = "********"

# Paths a remote client may reach with no gate configured: public share
# links only ("anyone with the link" by design — see chat.py). /api/health
# is deliberately not here; it describes installed models and components.
_ALWAYS_OPEN_PREFIXES = ("/api/share/",)
_ALWAYS_OPEN: set[str] = set()

_LOCAL_HOSTNAMES = {"localhost", "tauri.localhost"}
_LOOPBACK_BINDS = {"", "127.0.0.1", "::1", "localhost"}


def redact_config(data: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in data.items() if k not in HIDDEN_KEYS}
    for key in SECRET_KEYS:
        if key in out:
            out[key] = REDACTED if out[key] else ""
    return out


def strip_redacted(patch: dict[str, Any]) -> dict[str, Any]:
    """Drop secret fields the client echoed back unchanged."""
    return {k: v for k, v in patch.items() if not (k in SECRET_KEYS and v == REDACTED)}


def is_sensitive_key(key: str) -> bool:
    return key in SECRET_KEYS or key in HIDDEN_KEYS


@lru_cache(maxsize=8)
def _parse_networks(raw: str) -> tuple[tuple, frozenset]:
    nets, names = [], set()
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            names.add(part.lower())
    return tuple(nets), frozenset(names)


def _trusted_networks_active() -> bool:
    return os.environ.get("ZENITH_HOST_BIND", "").strip() in _LOOPBACK_BINDS


def is_local_client(host: str | None) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback:
            return True
        # IPv4-mapped loopback (::ffff:127.0.0.1) from dual-stack sockets.
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None and mapped.is_loopback:
            return True
    if not _trusted_networks_active():
        return False
    nets, names = _parse_networks(os.environ.get("ZENITH_TRUSTED_NETWORKS", ""))
    if host.lower() in names:
        return True
    return ip is not None and any(ip in n for n in nets)


def _allowed_hostnames() -> set[str]:
    names = {h.strip().lower() for h in os.environ.get("ZENITH_ALLOWED_HOSTS", "").split(",") if h.strip()}
    names.update(str(h).lower() for h in (settings.get("allowed_hosts") or []))
    return names


def host_header_allowed(host_header: str) -> bool:
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8420
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True  # a literal IP can't be a rebinding attack
    except ValueError:
        pass
    if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
        return True
    return host in _allowed_hostnames()


def shared_secret_active() -> bool:
    return bool(settings.get("auth_enabled", False)) and bool(settings.get("auth_shared_secret"))


def remote_gate_configured() -> bool:
    from app.api import lock as lock_api

    return shared_secret_active() or lock_api.is_locked()


class NetworkGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api/"):
            return await call_next(request)
        client = request.client.host if request.client else None
        if is_local_client(client):
            if not host_header_allowed(request.headers.get("host", "")):
                return JSONResponse(
                    {"detail": "Host header not allowed. Add it to ZENITH_ALLOWED_HOSTS if this is intentional."},
                    status_code=421,
                )
            return await call_next(request)
        if path in _ALWAYS_OPEN or path.startswith(_ALWAYS_OPEN_PREFIXES):
            return await call_next(request)
        if not remote_gate_configured():
            return JSONResponse(
                {
                    "detail": (
                        f"Remote access is blocked: this request came from {client}, not this machine. "
                        "Set a passcode (Settings → Data) or enable shared-secret auth to allow other devices."
                    ),
                    "code": "remote_access_blocked",
                },
                status_code=403,
            )
        return await call_next(request)


class SharedSecretAuth(BaseHTTPMiddleware):
    """Optional bearer-token gate, read live from settings so toggling it
    takes effect without a restart. Callers send
    `Authorization: Bearer <secret>` or `X-Zenith-Secret: <secret>`."""

    _OPEN = {"/api/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            not shared_secret_active()
            or request.method == "OPTIONS"
            or path in self._OPEN
            or path.startswith("/docs")
            or path.startswith(_ALWAYS_OPEN_PREFIXES)
        ):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else request.headers.get("x-zenith-secret", "")
        secret = str(settings.get("auth_shared_secret", ""))
        if not hmac.compare_digest(token.encode(), secret.encode()):
            return JSONResponse(
                {"detail": "Unauthorized — set Authorization: Bearer <auth_shared_secret>", "code": "auth_required"},
                status_code=401,
            )
        return await call_next(request)


class AttemptLimiter:
    """Per-key failed-attempt backoff for the passcode endpoint. The first
    few failures are free (typos); after that each failure doubles the
    wait, capped at 15 minutes. In-memory: a restart resets it, which is
    fine — a restart needs local access anyway."""

    FREE_ATTEMPTS = 5
    BASE_DELAY = 30.0
    MAX_DELAY = 15 * 60.0

    def __init__(self) -> None:
        self._state: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> float:
        with self._lock:
            failures, until = self._state.get(key, (0, 0.0))
        return max(0.0, until - time.monotonic())

    def fail(self, key: str) -> None:
        with self._lock:
            failures, _ = self._state.get(key, (0, 0.0))
            failures += 1
            delay = 0.0
            if failures > self.FREE_ATTEMPTS:
                delay = min(self.MAX_DELAY, self.BASE_DELAY * 2 ** (failures - self.FREE_ATTEMPTS - 1))
            self._state[key] = (failures, time.monotonic() + delay)

    def succeed(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._state.clear()


passcode_limiter = AttemptLimiter()
