"""Webhook signing/retry/SSRF guard, backup integrity + zip-slip safety,
and the diagnostic bundle's redaction."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import zipfile

import httpx
import pytest

from app.services import webhook_service


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_check_target_blocks_metadata_and_bad_schemes():
    for bad in ("file:///etc/passwd", "ftp://x/y", "http://169.254.169.254/latest", "http://metadata.google.internal/"):
        with pytest.raises(webhook_service.UnsafeTarget):
            webhook_service.check_target(bad)
    webhook_service.check_target("http://127.0.0.1:9000/hook")  # local receivers are the point


def test_delivery_is_signed_and_retried(client):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(503 if len(seen) < 2 else 200)

    async def go():
        async with _client(handler) as c:
            return await webhook_service.deliver("http://127.0.0.1:9/h", "test", {"a": 1}, secret="s3cret",
                                                 client=c, backoff=(0, 0, 0))

    res = asyncio.run(go())
    assert res["status"] == "delivered" and res["attempts"] == 2
    req = seen[-1]
    ts = req.headers["X-Zenith-Timestamp"]
    want = "sha256=" + hmac.new(b"s3cret", ts.encode() + b"." + req.content, hashlib.sha256).hexdigest()
    assert req.headers["X-Zenith-Signature"] == want
    assert seen[0].headers["X-Zenith-Delivery"] == seen[1].headers["X-Zenith-Delivery"]
    assert webhook_service.deliveries()[0]["status"] == "delivered"


def test_4xx_not_retried_and_hook_auto_disables(client, monkeypatch):
    r = client.post("/api/webhooks", json={"url": "http://127.0.0.1:9/h", "event_types": ["digest_generated"]})
    hook = r.json()
    assert hook["secret"].startswith("whsec_")
    assert "secret" not in client.get("/api/webhooks").json()[0]
    calls = []

    async def fake_post(self, url, content=None, headers=None, **kw):
        calls.append(url)
        return httpx.Response(404)

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    for _ in range(webhook_service.DISABLE_AFTER):
        asyncio.run(webhook_service.dispatch("digest_generated", {}))
    assert len(calls) == webhook_service.DISABLE_AFTER  # one attempt each
    listed = client.get("/api/webhooks").json()[0]
    assert listed["enabled"] is False and "Turned off" in listed["disabled_reason"]
    assert client.patch(f"/api/webhooks/{hook['id']}", json={"enabled": True}).status_code == 200
    assert client.get("/api/webhooks").json()[0]["consecutive_failures"] == 0


def test_create_rejects_unsafe_url(client):
    r = client.post("/api/webhooks", json={"url": "http://169.254.169.254/", "event_types": ["digest_generated"]})
    assert r.status_code == 422


def test_backup_manifest_and_inspect(client):
    raw = client.get("/api/backup/create").content
    zf = zipfile.ZipFile(io.BytesIO(raw))
    m = json.loads(zf.read("manifest.json"))
    assert m["format"] == 2 and m["schema_version"] and "zenith.db" in m["sha256"]
    rep = client.post("/api/backup/inspect", files={"file": ("b.zip", raw, "application/zip")}).json()
    assert rep["ok"] is True and rep["schema_version"] == rep["current_schema_version"]
    assert "conversations" in rep["counts"]


def _tamper(raw: bytes, extra: dict[str, bytes] | None = None, db: bytes | None = None) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(raw))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for n in src.namelist():
            zf.writestr(n, db if (db is not None and n == "zenith.db") else src.read(n))
        for n, b in (extra or {}).items():
            zf.writestr(n, b)
    return out.getvalue()


def test_restore_refuses_corrupt_backup(client):
    raw = client.get("/api/backup/create").content
    bad = _tamper(raw, db=b"not a database")
    rep = client.post("/api/backup/inspect", files={"file": ("b.zip", bad, "application/zip")}).json()
    assert rep["ok"] is False
    r = client.post("/api/backup/restore", files={"file": ("b.zip", bad, "application/zip")}, data={"confirm": "true"})
    assert r.status_code == 400 and "nothing was touched" in r.json()["detail"]


def test_restore_skips_zip_slip_paths(client, temp_data_dir):
    raw = client.get("/api/backup/create").content
    evil = _tamper(raw, extra={"uploads/../../escaped.txt": b"x", "uploads/ok/fine.txt": b"y"})
    r = client.post("/api/backup/restore", files={"file": ("b.zip", evil, "application/zip")}, data={"confirm": "true"})
    assert r.status_code == 200
    assert not (temp_data_dir.parent / "escaped.txt").exists()
    assert not (temp_data_dir / "escaped.txt").exists()
    from app.core.config import upload_dir
    assert (upload_dir() / "ok" / "fine.txt").read_bytes() == b"y"


def test_diagnostic_bundle_redacts(client):
    from app.core.config import settings
    from app.services import support_bundle

    settings.update({"email_address": "me@example.com", "email_password": "hunter2-pass"})
    assert "<email>" in support_bundle.scrub("contact me@example.com now")
    assert "sk-abcdefghijklmnop" not in support_bundle.scrub("key sk-abcdefghijklmnop")
    files = client.get("/api/diagnostics/bundle/preview").json()["files"]
    assert {"system.json", "config.redacted.json", "zenith.log.tail.txt", "README.txt"} <= set(files)
    blob = json.dumps(files)
    assert "hunter2-pass" not in blob and "me@example.com" not in blob
    info = json.loads(files["system.json"])
    assert info["database"]["up_to_date"] is True
    r = client.get("/api/diagnostics/bundle")
    assert r.status_code == 200 and zipfile.ZipFile(io.BytesIO(r.content)).namelist()
