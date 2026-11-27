"""Passcode change needs the current passcode; recovery code reset;
signing out other sessions; auto-lock setting."""
from __future__ import annotations


def _h(token):
    return {"x-zenith-unlock": token}


def test_full_lock_lifecycle(client):
    r = client.post("/api/lock/set", json={"passcode": "1234"}).json()
    token, code = r["token"], r["recovery_code"]
    assert len(code.replace("-", "")) == 20
    st = client.get("/api/lock/status").json()
    assert st["enabled"] and st["has_recovery"] and st["auto_lock_minutes"] == 0
    assert "lock_recovery_hash" not in client.get("/api/config", headers=_h(token)).json()

    # Changing needs the current passcode as well as an unlocked session.
    assert client.post("/api/lock/set", json={"passcode": "5678"}, headers=_h(token)).status_code == 401
    r = client.post("/api/lock/set", json={"passcode": "5678", "current_passcode": "1234"}, headers=_h(token))
    assert r.status_code == 200 and "recovery_code" not in r.json()
    token = r.json()["token"]

    assert client.post("/api/lock/settings", json={"auto_lock_minutes": 15}, headers=_h(token)).status_code == 200
    assert client.get("/api/lock/status").json()["auto_lock_minutes"] == 15

    # Sign out other sessions: the old token stops working, the returned one works.
    other = client.post("/api/lock/verify", json={"passcode": "5678"}).json()["token"]
    fresh = client.post("/api/lock/revoke-sessions", headers=_h(token)).json()["token"]
    from app.api.lock import token_valid
    assert not token_valid(other) and token_valid(fresh)

    # Forgot passcode: a wrong code fails, the right one resets and is single-use.
    assert client.post("/api/lock/reset", json={"recovery_code": "AAAA-BBBB", "passcode": "9999"}).status_code == 401
    r = client.post("/api/lock/reset", json={"recovery_code": code.lower(), "passcode": "9999"})
    assert r.status_code == 200, r.text
    assert r.json()["recovery_code"] != code
    assert not token_valid(fresh)
    assert client.post("/api/lock/verify", json={"passcode": "9999"}).status_code == 200
    from app.core.security import passcode_limiter
    passcode_limiter._fails.clear() if hasattr(passcode_limiter, "_fails") else None
    assert client.post("/api/lock/reset", json={"recovery_code": code, "passcode": "0000"}).status_code in (401, 429)
