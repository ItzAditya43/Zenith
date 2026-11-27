"""API keys: create once, scopes, remote access, lock bypass, rotation,
revocation, rate limit, and the version header."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _remote(app):
    # A client that looks like another device on the network.
    return TestClient(app, client=("192.168.1.50", 50000))


def test_key_lifecycle(client):
    from app.main import app

    k = client.post("/api/api-keys", json={"name": "script", "scope": "read"}).json()
    assert k["key"].startswith("zk_") and "key" not in client.get("/api/api-keys").json()[0]
    h = {"Authorization": f"Bearer {k['key']}"}
    r = client.get("/api/conversations", headers=h)
    assert r.status_code == 200 and r.headers["X-Zenith-API-Version"] == "1"
    assert client.post("/api/conversations", json={"title": "x"}, headers=h).status_code == 403  # read-only
    assert client.post("/api/api-keys", json={"name": "y"}, headers=h).status_code in (403,)  # keys can't mint keys

    remote = _remote(app)
    assert remote.get("/api/conversations").status_code == 403          # no key, no gate: blocked
    assert remote.get("/api/conversations", headers=h).status_code == 200  # a key is an explicit grant

    new = client.post(f"/api/api-keys/{k['id']}/rotate").json()
    assert client.get("/api/conversations", headers=h).status_code == 401
    h2 = {"Authorization": f"Bearer {new['key']}"}
    assert client.get("/api/conversations", headers=h2).status_code == 200
    client.delete(f"/api/api-keys/{new['id']}")
    assert client.get("/api/conversations", headers=h2).status_code == 401
    assert client.get("/api/conversations", headers={"Authorization": "Bearer zk_nope_nope"}).status_code == 401


def test_write_key_passes_passcode_lock_and_rate_limit(client):
    from app.core.config import settings

    w = client.post("/api/api-keys", json={"name": "bot", "scope": "write"}).json()
    h = {"Authorization": f"Bearer {w['key']}"}
    assert client.post("/api/lock/set", json={"passcode": "1234"}).status_code == 200
    assert client.get("/api/conversations").status_code == 423       # locked for the UI
    assert client.post("/api/conversations", json={"title": "from a script"}, headers=h).status_code == 200
    settings.update({"api_key_rate_per_minute": 3})
    try:
        codes = [client.get("/api/conversations", headers=h).status_code for _ in range(4)]
        assert codes[-1] == 429
    finally:
        settings.update({"api_key_rate_per_minute": 120})


def test_version(client):
    assert client.get("/api/version").json()["api_version"] == "1"


@pytest.mark.parametrize("scope", ["admin", ""])
def test_bad_scope(client, scope):
    r = client.post("/api/api-keys", json={"name": "x", "scope": scope})
    assert r.status_code == (422 if scope else 200)
