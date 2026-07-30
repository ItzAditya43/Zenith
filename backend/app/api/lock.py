"""App-level passcode lock.

Gates the UI/API behind a passcode so other users of the same machine can't
open your chats. This is NOT at-rest encryption — the SQLite file is still
readable by anyone with filesystem access; it's a login gate, not a vault.

  GET  /api/lock/status   — {enabled} (always reachable, so the UI knows to lock)
  POST /api/lock/verify   — {passcode} -> {ok, token}; token unlocks subsequent requests
  POST /api/lock/set      — {passcode} set/change the passcode (must be unlocked if already set)
  POST /api/lock/disable  — {passcode} turn the lock off
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/lock", tags=["lock"])

# Fixed salt: this is a local, single-user convenience lock, not a public
# credential store — a static salt still stops the hash from being a bare,
# rainbow-table-trivial sha256 of a short passcode.
_SALT = "cortex-lock-v1"


def hash_passcode(passcode: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", passcode.encode(), _SALT.encode(), 120_000).hex()


def _current_hash() -> str:
    return str(settings.get("lock_pass_hash", ""))


def is_locked() -> bool:
    return bool(settings.get("lock_enabled", False)) and bool(_current_hash())


def token_valid(token: str) -> bool:
    """The unlock token issued on verify is the stored hash itself — sending
    it back proves the client passed the passcode check. Adequate over a
    local loopback/LAN connection for a single-user convenience lock."""
    h = _current_hash()
    return bool(h) and token == h


@router.get("/status")
async def status():
    return {"enabled": is_locked()}


@router.post("/verify")
async def verify(body: dict):
    passcode = str(body.get("passcode", ""))
    if not is_locked():
        return {"ok": True, "token": ""}  # nothing to unlock
    if hash_passcode(passcode) != _current_hash():
        raise HTTPException(401, "Incorrect passcode.")
    return {"ok": True, "token": _current_hash()}


@router.post("/set")
async def set_passcode(body: dict, request: Request):
    passcode = str(body.get("passcode", "")).strip()
    if len(passcode) < 4:
        raise HTTPException(400, "Passcode must be at least 4 characters.")
    # If a lock is already active, require the caller to be unlocked before
    # changing it (the lock middleware already enforces this for /set, but
    # guard here too in case the middleware allowlist ever changes).
    if is_locked() and not token_valid(request.headers.get("x-cortex-unlock", "")):
        raise HTTPException(401, "Unlock first to change the passcode.")
    new_hash = hash_passcode(passcode)
    settings.set("lock_pass_hash", new_hash)
    settings.set("lock_enabled", True)
    return {"ok": True, "token": new_hash}


@router.post("/disable")
async def disable(body: dict):
    passcode = str(body.get("passcode", ""))
    if is_locked() and hash_passcode(passcode) != _current_hash():
        raise HTTPException(401, "Incorrect passcode.")
    settings.set("lock_enabled", False)
    settings.set("lock_pass_hash", "")
    return {"ok": True}
