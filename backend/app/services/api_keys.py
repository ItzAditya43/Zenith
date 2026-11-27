"""API keys for scripts and other apps.

A key looks like `zk_<id>_<secret>`; only a SHA-256 of it is stored, so
it's shown once at creation and can't be recovered — rotate it instead.
Scopes: `read` (GET/HEAD only) or `write` (everything). A valid key works
from other devices and while the passcode lock is on, since it's an
explicit grant you made for that purpose. Each key is rate-limited.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque

from app.core.config import settings
from app.db.storage import _conn

PREFIX = "zk_"
_hits: dict[str, deque] = {}
_last_touch: dict[str, float] = {}


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create(name: str, scope: str = "read") -> dict:
    if scope not in ("read", "write"):
        raise ValueError("Scope must be read or write.")
    kid = secrets.token_hex(4)
    key = f"{PREFIX}{kid}_{secrets.token_urlsafe(24)}"
    now = time.time()
    with _conn() as conn:
        conn.execute("INSERT INTO api_keys (id, name, scope, key_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                     (kid, (name or "API key").strip()[:60], scope, _hash(key), now))
    return {"id": kid, "name": name, "scope": scope, "key": key, "created_at": now}


def list_keys() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT id, name, scope, created_at, last_used_at, revoked_at FROM api_keys ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def revoke(kid: str) -> bool:
    with _conn() as conn:
        return conn.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (time.time(), kid)).rowcount > 0


def rotate(kid: str) -> dict:
    """A new key with the same name and scope; the old one stops working."""
    with _conn() as conn:
        r = conn.execute("SELECT name, scope FROM api_keys WHERE id = ? AND revoked_at IS NULL", (kid,)).fetchone()
    if not r:
        raise LookupError("No active key with that id.")
    new = create(r["name"], r["scope"])
    revoke(kid)
    return new


def verify(token: str) -> dict | None:
    """The key's row if `token` is a live key, else None."""
    if not token.startswith(PREFIX) or token.count("_") < 2:
        return None
    kid = token[len(PREFIX):].split("_", 1)[0]
    with _conn() as conn:
        r = conn.execute("SELECT id, name, scope, key_hash, revoked_at FROM api_keys WHERE id = ?", (kid,)).fetchone()
    if not r or r["revoked_at"] or not hmac.compare_digest(r["key_hash"], _hash(token)):
        return None
    now = time.time()
    if now - _last_touch.get(kid, 0) > 30:  # don't write on every request
        _last_touch[kid] = now
        with _conn() as conn:
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, kid))
    return dict(r)


def allow_rate(kid: str) -> bool:
    limit = int(settings.get("api_key_rate_per_minute", 120))
    q = _hits.setdefault(kid, deque())
    now = time.monotonic()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True
