"""Network exposure, secret redaction and passcode hardening — see
app/core/security.py and app/api/lock.py."""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_limiter():
    from app.core.security import passcode_limiter

    passcode_limiter.reset()
    yield
    passcode_limiter.reset()


def _remote_client(app, ip="192.168.1.50"):
    return TestClient(app, client=(ip, 51000))


# --- remote clients ---------------------------------------------------------


def test_remote_client_blocked_without_a_gate(client):
    from app.main import app

    with _remote_client(app) as remote:
        res = remote.get("/api/config")
    assert res.status_code == 403
    assert res.json()["code"] == "remote_access_blocked"


def test_remote_client_cannot_enable_agent_mode(client):
    from app.core.config import settings
    from app.main import app

    with _remote_client(app) as remote:
        res = remote.patch("/api/config", json={"agent_enabled": True, "agent_mode": "full"})
    assert res.status_code == 403
    assert settings.get("agent_enabled") is False


def test_remote_health_is_not_open_without_a_gate(client):
    from app.main import app

    with _remote_client(app) as remote:
        assert remote.get("/api/health").status_code == 403


def test_remote_client_reaches_passcode_gate_once_lock_is_set(client):
    from app.main import app

    assert client.post("/api/lock/set", json={"passcode": "4821"}).status_code == 200
    with _remote_client(app) as remote:
        assert remote.get("/api/config").status_code == 423  # gated, not blocked
        token = remote.post("/api/lock/verify", json={"passcode": "4821"}).json()["token"]
        assert remote.get("/api/config", headers={"X-Zenith-Unlock": token}).status_code == 200


def test_remote_share_links_stay_public(client):
    from app.main import app

    with _remote_client(app) as remote:
        # Unknown token -> 404 from the route itself, i.e. the guard let it through.
        assert remote.get("/api/share/nope").status_code == 404


def test_trusted_networks_ignored_when_published_beyond_loopback(monkeypatch):
    from app.core.security import is_local_client

    monkeypatch.setenv("ZENITH_TRUSTED_NETWORKS", "172.16.0.0/12")
    monkeypatch.setenv("ZENITH_HOST_BIND", "127.0.0.1")
    assert is_local_client("172.17.0.1")
    monkeypatch.setenv("ZENITH_HOST_BIND", "0.0.0.0")
    assert not is_local_client("172.17.0.1")
    assert is_local_client("127.0.0.1")
    assert is_local_client("::ffff:127.0.0.1")


# --- DNS rebinding ----------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "ok"),
    [
        ("localhost:8420", True),
        ("127.0.0.1:8420", True),
        ("[::1]:8420", True),
        ("192.168.1.20:8420", True),
        ("tauri.localhost", True),
        ("evil.example.com", False),
        ("localhost.evil.example.com:8420", False),
        ("", False),
    ],
)
def test_host_header_allowlist(host, ok):
    from app.core.security import host_header_allowed

    assert host_header_allowed(host) is ok


def test_local_request_with_foreign_host_header_rejected(client):
    res = client.get("/api/config", headers={"Host": "rebind.attacker.test"})
    assert res.status_code == 421


# --- secret redaction -------------------------------------------------------


def test_config_get_redacts_secrets(client):
    from app.core.config import settings

    settings.update({"email_password": "hunter2", "auth_shared_secret": ""})
    client.post("/api/lock/set", json={"passcode": "4821"})
    token = client.post("/api/lock/verify", json={"passcode": "4821"}).json()["token"]
    res = client.get("/api/config", headers={"X-Zenith-Unlock": token})
    body = res.json()
    assert body["email_password"] == "********"
    assert body["auth_shared_secret"] == ""
    assert "lock_pass_hash" not in body
    assert "hunter2" not in res.text
    assert "public" not in res.headers["cache-control"]


def test_config_patch_echoing_redacted_value_keeps_secret(client):
    from app.core.config import settings

    settings.update({"email_password": "hunter2"})
    res = client.patch("/api/config", json={"email_password": "********", "email_username": "me"})
    assert res.status_code == 200
    assert res.json()["email_password"] == "********"
    assert settings.get("email_password") == "hunter2"
    assert settings.get("email_username") == "me"


def test_settings_history_never_stores_secret_values(client):
    from app.core.config import settings
    from app.services import settings_history_service

    settings.update({"email_password": "hunter2"})
    rows = settings_history_service.list_history(key="email_password")
    assert rows and all("hunter2" not in str(r) for r in rows)
    with pytest.raises(PermissionError):
        settings_history_service.revert_to(rows[0]["id"])
    assert client.post(f"/api/settings/history/{rows[0]['id']}/revert").status_code == 400


def test_history_migration_scrubs_existing_secret_rows(temp_data_dir):
    import sqlite3

    from app.db.migrations import _redact_secret_history, _settings_history_table

    conn = sqlite3.connect(":memory:")
    _settings_history_table(conn)
    conn.execute("INSERT INTO settings_history VALUES ('a', 'email_password', '\"\"', '\"hunter2\"', 1)")
    conn.execute("INSERT INTO settings_history VALUES ('b', 'agent_mode', '\"manual\"', '\"full\"', 2)")
    _redact_secret_history(conn)
    rows = dict((r[0], r[1:]) for r in conn.execute("SELECT id, old_value, new_value FROM settings_history"))
    assert rows["a"] == ('""', '"[redacted]"')
    assert rows["b"] == ('"manual"', '"full"')


# --- shared-secret auth -----------------------------------------------------


def test_shared_secret_auth_is_live_and_constant_time(client):
    from app.core.config import settings

    settings.update({"auth_enabled": True, "auth_shared_secret": "s3cret"})
    res = client.get("/api/config")
    assert res.status_code == 401
    assert res.json()["code"] == "auth_required"
    assert client.get("/api/config", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/config", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/config", headers={"X-Zenith-Secret": "s3cret"}).status_code == 200
    settings.update({"auth_enabled": False})
    assert client.get("/api/config").status_code == 200


def test_remote_client_allowed_through_with_shared_secret(client):
    from app.core.config import settings
    from app.main import app

    settings.update({"auth_enabled": True, "auth_shared_secret": "s3cret"})
    with _remote_client(app) as remote:
        assert remote.get("/api/config").status_code == 401
        assert remote.get("/api/config", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_cors_headers_present_on_gate_refusals(client):
    from app.core.config import settings

    settings.update({"auth_enabled": True, "auth_shared_secret": "s3cret"})
    res = client.get("/api/config", headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"


# --- env overrides ----------------------------------------------------------


def test_env_overrides_apply_but_are_not_persisted(temp_data_dir, monkeypatch):
    import json

    from app.core import config as cfg

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SHARED_SECRET", "from-env")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://a.test, http://b.test")
    cfg.settings.reload()
    assert cfg.settings.get("auth_enabled") is True
    assert cfg.settings.get("auth_shared_secret") == "from-env"
    assert cfg.settings.get("cors_allow_origins") == ["http://a.test", "http://b.test"]

    cfg.settings.set("system_prompt", "hi")
    on_disk = json.loads(cfg.config_path().read_text())
    assert on_disk["auth_enabled"] is False
    assert on_disk["auth_shared_secret"] in ("", None)

    monkeypatch.delenv("AUTH_ENABLED")
    monkeypatch.delenv("AUTH_SHARED_SECRET")
    monkeypatch.delenv("CORS_ALLOW_ORIGINS")
    cfg.settings.reload()
    assert cfg.settings.get("auth_enabled") is False


def test_empty_env_var_does_not_override(temp_data_dir, monkeypatch):
    from app.core import config as cfg

    cfg.settings.set("auth_enabled", True)
    monkeypatch.setenv("AUTH_ENABLED", "")
    cfg.settings.reload()
    assert cfg.settings.get("auth_enabled") is True


def test_zenith_env_names_take_precedence(monkeypatch):
    from app.core.config import env

    monkeypatch.setenv("CORTEX_PORT", "1")
    assert env("PORT") == "1"
    monkeypatch.setenv("ZENITH_PORT", "2")
    assert env("PORT") == "2"


# --- passcode lock ----------------------------------------------------------


def test_unlock_token_is_not_the_stored_hash(client):
    from app.core.config import settings

    token = client.post("/api/lock/set", json={"passcode": "4821"}).json()["token"]
    stored = settings.get("lock_pass_hash")
    assert stored.startswith("pbkdf2_sha256$")
    assert token and token != stored
    assert client.get("/api/config", headers={"X-Zenith-Unlock": stored}).status_code == 423
    assert client.get("/api/config", headers={"X-Zenith-Unlock": token}).status_code == 200


def test_changing_passcode_invalidates_old_tokens(client):
    old = client.post("/api/lock/set", json={"passcode": "4821"}).json()["token"]
    new = client.post("/api/lock/set", json={"passcode": "9999"}, headers={"X-Zenith-Unlock": old}).json()["token"]
    assert client.get("/api/config", headers={"X-Zenith-Unlock": old}).status_code == 423
    assert client.get("/api/config", headers={"X-Zenith-Unlock": new}).status_code == 200


def test_legacy_hash_still_verifies_and_is_upgraded(client):
    from app.core.config import settings

    legacy = hashlib.pbkdf2_hmac("sha256", b"4821", b"cortex-lock-v1", 120_000).hex()
    settings.update({"lock_enabled": True, "lock_pass_hash": legacy})
    assert client.post("/api/lock/verify", json={"passcode": "0000"}).status_code == 401
    res = client.post("/api/lock/verify", json={"passcode": "4821"})
    assert res.status_code == 200
    assert settings.get("lock_pass_hash").startswith("pbkdf2_sha256$")
    assert client.get("/api/config", headers={"X-Zenith-Unlock": res.json()["token"]}).status_code == 200


def test_passcode_brute_force_is_throttled(client):
    from app.core.security import AttemptLimiter

    client.post("/api/lock/set", json={"passcode": "4821"})
    for _ in range(AttemptLimiter.FREE_ATTEMPTS):
        assert client.post("/api/lock/verify", json={"passcode": "0000"}).status_code == 401
    assert client.post("/api/lock/verify", json={"passcode": "0000"}).status_code == 401  # starts the backoff
    res = client.post("/api/lock/verify", json={"passcode": "4821"})
    assert res.status_code == 429  # even the right passcode waits out the backoff
    assert int(res.headers["retry-after"]) > 0


def test_disable_requires_passcode_and_is_throttled(client):
    from app.core.security import AttemptLimiter

    client.post("/api/lock/set", json={"passcode": "4821"})
    for _ in range(AttemptLimiter.FREE_ATTEMPTS + 1):
        client.post("/api/lock/disable", json={"passcode": "0000"})
    assert client.post("/api/lock/disable", json={"passcode": "4821"}).status_code == 429


def test_limiter_backoff_grows_and_caps():
    from app.core.security import AttemptLimiter

    lim = AttemptLimiter()
    waits = []
    for _ in range(AttemptLimiter.FREE_ATTEMPTS + 8):
        lim.fail("k")
        waits.append(round(lim.retry_after("k")))
    assert all(w == 0 for w in waits[: AttemptLimiter.FREE_ATTEMPTS])
    tail = waits[AttemptLimiter.FREE_ATTEMPTS:]
    assert tail == sorted(tail) and tail[-1] <= AttemptLimiter.MAX_DELAY
    lim.succeed("k")
    assert lim.retry_after("k") == 0


def test_profiles_get_separate_data_dirs(monkeypatch, tmp_path):
    from app.core import config as cfg

    monkeypatch.setenv("ZENITH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ZENITH_PROFILE", raising=False)
    assert cfg.data_dir() == tmp_path
    monkeypatch.setenv("ZENITH_PROFILE", "alice")
    assert cfg.data_dir() == tmp_path / "profiles" / "alice"
    assert cfg.db_path() == tmp_path / "profiles" / "alice" / "zenith.db"
    for bad in ("../etc", "a/b", "-leading", "x" * 41):
        monkeypatch.setenv("ZENITH_PROFILE", bad)
        if bad.strip():
            with pytest.raises(ValueError):
                cfg.profile_name()
