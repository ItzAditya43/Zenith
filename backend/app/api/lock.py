"""App-level passcode lock.

Gates the UI/API behind a passcode so other users of the same machine (or
other devices on the network — see app/core/security.py) can't open your
chats. This is NOT at-rest encryption — the SQLite file is still readable by
anyone with filesystem access; it's a login gate, not a vault.

  GET  /api/lock/status          — {enabled, auto_lock_minutes, has_recovery, retry_after}
  POST /api/lock/verify          — {passcode} -> {ok, token}; token unlocks subsequent requests
  POST /api/lock/set             — {passcode, current_passcode?} set/change; returns a recovery code
                                   the first time (and whenever regenerate_recovery is true)
  POST /api/lock/reset           — {recovery_code, passcode}: forgot-passcode path
  POST /api/lock/revoke-sessions — sign out every other browser/device (unlocked callers only)
  POST /api/lock/settings        — {auto_lock_minutes}
  POST /api/lock/disable         — {passcode} turn the lock off

Last-resort recovery without the code: with access to this computer's
files, clear `lock_pass_hash` in config.json and restart Zenith. That is
also why the lock is not protection against someone with file access.
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
    """Unlock token = HMAC(machine key, stored hash + session epoch). Proves
    the client passed the passcode check without the token being the hash
    itself; changing the passcode or bumping the epoch ("sign out other
    devices") invalidates every outstanding token."""
    from app.services.crypto_service import machine_key

    epoch = str(settings.get("lock_session_epoch", 0) or 0)
    msg = b"zenith-unlock:" + stored_hash.encode() + (b":" + epoch.encode() if epoch != "0" else b"")
    return hmac.new(machine_key(), msg, hashlib.sha256).hexdigest()


def _new_recovery_code() -> tuple[str, str]:
    import secrets

    raw = secrets.token_hex(10).upper()
    code = "-".join(raw[i:i + 4] for i in range(0, 20, 4))
    return code, hash_passcode(code.replace("-", ""))


def _norm_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


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
async def status(request: Request):
    return {
        "enabled": is_locked(),
        "auto_lock_minutes": int(settings.get("lock_auto_minutes", 0) or 0),
        "has_recovery": bool(settings.get("lock_recovery_hash", "")),
        "retry_after": int(passcode_limiter.retry_after(_client_key(request)) + 0.999),
    }


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
    if is_locked():
        if not token_valid(request.headers.get("x-zenith-unlock", "")):
            raise HTTPException(401, "Unlock first to change the passcode.")
        _verify_or_raise(str(body.get("current_passcode", "")), request)
    new_hash = hash_passcode(passcode)
    first = not is_locked()
    settings.set("lock_pass_hash", new_hash)
    settings.set("lock_enabled", True)
    out = {"ok": True, "token": _issue_token(new_hash)}
    if first or body.get("regenerate_recovery") or not settings.get("lock_recovery_hash", ""):
        code, code_hash = _new_recovery_code()
        settings.set("lock_recovery_hash", code_hash)
        out["recovery_code"] = code
    return out


@router.post("/reset")
async def reset_with_recovery(body: dict, request: Request):
    """Forgot the passcode: a valid recovery code sets a new one. The
    code is single-use — a fresh one is returned."""
    _require_not_throttled(request)
    stored = str(settings.get("lock_recovery_hash", ""))
    code = _norm_code(str(body.get("recovery_code", "")))
    if not is_locked() or not stored or not check_passcode(code, stored):
        passcode_limiter.fail(_client_key(request))
        raise HTTPException(401, "That recovery code isn't right.")
    passcode_limiter.succeed(_client_key(request))
    passcode = str(body.get("passcode", "")).strip()
    if len(passcode) < 4:
        raise HTTPException(400, "Passcode must be at least 4 characters.")
    new_hash = hash_passcode(passcode)
    settings.set("lock_pass_hash", new_hash)
    settings.set("lock_session_epoch", int(settings.get("lock_session_epoch", 0) or 0) + 1)
    new_code, code_hash = _new_recovery_code()
    settings.set("lock_recovery_hash", code_hash)
    log.info("lock.reset_with_recovery")
    return {"ok": True, "token": _issue_token(new_hash), "recovery_code": new_code}


def _require_unlocked(request: Request) -> None:
    if is_locked() and not token_valid(request.headers.get("x-zenith-unlock", "")):
        raise HTTPException(401, "Unlock first.")


@router.post("/revoke-sessions")
async def revoke_sessions(request: Request):
    _require_unlocked(request)
    settings.set("lock_session_epoch", int(settings.get("lock_session_epoch", 0) or 0) + 1)
    return {"ok": True, "token": _issue_token(_current_hash()) if is_locked() else ""}


@router.post("/settings")
async def lock_settings(body: dict, request: Request):
    _require_unlocked(request)
    minutes = int(body.get("auto_lock_minutes", 0) or 0)
    if minutes < 0 or minutes > 1440:
        raise HTTPException(400, "auto_lock_minutes must be between 0 and 1440.")
    settings.set("lock_auto_minutes", minutes)
    return {"ok": True, "auto_lock_minutes": minutes}


@router.post("/disable")
async def disable(body: dict, request: Request):
    passcode = str(body.get("passcode", ""))
    if is_locked():
        _verify_or_raise(passcode, request)
    settings.set("lock_enabled", False)
    settings.set("lock_pass_hash", "")
    settings.set("lock_recovery_hash", "")
    return {"ok": True}
