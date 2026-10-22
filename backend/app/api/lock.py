"""App-level passcode lock.

Gates the UI/API behind a passcode so other users of the same machine (or
other devices on the network — see app/core/security.py) can't open your
chats. This is NOT at-rest encryption — the SQLite file is still readable by
anyone with filesystem access; it's a login gate, not a vault.

  GET  /api/lock/status   — {enabled} (always reachable, so the UI knows to lock)
  POST /api/lock/verify   — {passcode} -> {ok, token}; token unlocks subsequent requests
  POST /api/lock/set      — {passcode} set/change the passcode (must be unlocked if already set)
  POST /api/lock/disable  — {passcode} turn the lock off
"""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import passcode_limiter

log = get_logger(__name__)
router = APIRouter(prefix="/api/lock", tags=["lock"])

_ITERATIONS = 600_000
_PREFIX = "pbkdf2_sha256"
# Pre-v0.1 hashes: bare hex, 120k iterations, one fixed salt. Still accepted
# so an existing passcode keeps working; upgraded on the next good verify.
_LEGACY_SALT = "cortex-lock-v1"
_LEGACY_ITERATIONS = 120_000


def hash_passcode(passcode: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", passcode.encode(), salt.encode(), _ITERATIONS).hex()
    return f"{_PREFIX}${_ITERATIONS}${salt}${digest}"


def _legacy_hash(passcode: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", passcode.encode(), _LEGACY_SALT.encode(), _LEGACY_ITERATIONS).hex()


def check_passcode(passcode: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith(_PREFIX + "$"):
        try:
            _, iterations, salt, digest = stored.split("$", 3)
            candidate = hashlib.pbkdf2_hmac("sha256", passcode.encode(), salt.encode(), int(iterations)).hex()
        except ValueError:
            return False
        return hmac.compare_digest(candidate, digest)
    return hmac.compare_digest(_legacy_hash(passcode), stored)


def _current_hash() -> str:
    return str(settings.get("lock_pass_hash", ""))


def is_locked() -> bool:
    return bool(settings.get("lock_enabled", False)) and bool(_current_hash())


def _issue_token(stored_hash: str) -> str:
    """Unlock token = HMAC(machine key, stored hash). Proves the client
    passed the passcode check without the token being the hash itself, and
    changing the passcode invalidates every outstanding token."""
    from app.services.crypto_service import machine_key

    return hmac.new(machine_key(), b"zenith-unlock:" + stored_hash.encode(), hashlib.sha256).hexdigest()


def token_valid(token: str) -> bool:
    h = _current_hash()
    return bool(h) and bool(token) and hmac.compare_digest(token, _issue_token(h))


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require_not_throttled(request: Request) -> None:
    wait = passcode_limiter.retry_after(_client_key(request))
    if wait > 0:
        raise HTTPException(429, f"Too many wrong passcodes — try again in {int(wait) + 1}s.",
                            headers={"Retry-After": str(int(wait) + 1)})


def _verify_or_raise(passcode: str, request: Request) -> None:
    _require_not_throttled(request)
    if not check_passcode(passcode, _current_hash()):
        passcode_limiter.fail(_client_key(request))
        log.warning("lock.verify_failed", client=_client_key(request))
        raise HTTPException(401, "Incorrect passcode.")
    passcode_limiter.succeed(_client_key(request))


@router.get("/status")
async def status():
    return {"enabled": is_locked()}


@router.post("/verify")
async def verify(body: dict, request: Request):
    passcode = str(body.get("passcode", ""))
    if not is_locked():
        return {"ok": True, "token": ""}  # nothing to unlock
    _verify_or_raise(passcode, request)
    stored = _current_hash()
    if not stored.startswith(_PREFIX + "$"):
        stored = hash_passcode(passcode)
        settings.set("lock_pass_hash", stored)
    return {"ok": True, "token": _issue_token(stored)}


@router.post("/set")
async def set_passcode(body: dict, request: Request):
    passcode = str(body.get("passcode", "")).strip()
    if len(passcode) < 4:
        raise HTTPException(400, "Passcode must be at least 4 characters.")
    # If a lock is already active, require the caller to be unlocked before
    # changing it (the lock middleware allowlists /api/lock/*, so this is
    # the only check).
    if is_locked() and not token_valid(request.headers.get("x-zenith-unlock", "")):
        raise HTTPException(401, "Unlock first to change the passcode.")
    new_hash = hash_passcode(passcode)
    settings.set("lock_pass_hash", new_hash)
    settings.set("lock_enabled", True)
    return {"ok": True, "token": _issue_token(new_hash)}


@router.post("/disable")
async def disable(body: dict, request: Request):
    passcode = str(body.get("passcode", ""))
    if is_locked():
        _verify_or_raise(passcode, request)
    settings.set("lock_enabled", False)
    settings.set("lock_pass_hash", "")
    return {"ok": True}
