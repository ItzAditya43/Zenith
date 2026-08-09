"""Outbound webhooks + automation rules — the internal event bus
(events.py) fans a real backend event out to both. Uses a fake httpx
transport so these tests never touch the network."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def temp_data_dir(monkeypatch):
    d = tempfile.mkdtemp(prefix="cortex-test-")
    monkeypatch.setenv("CORTEX_DATA_DIR", d)
    from app.core import config as cfg

    cfg.refresh_paths()
    cfg.settings.reload()
    yield Path(d)
    cfg.refresh_paths()
    cfg.settings.reload()


@pytest.fixture
def client(temp_data_dir):
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_event_types_listed(client):
    r = client.get("/api/automation/event-types")
    assert r.status_code == 200
    assert "digest_generated" in r.json()
    assert "urgent_email" in r.json()


def test_webhook_crud(client):
    r = client.post("/api/webhooks", json={"url": "http://localhost:9/hook", "event_types": ["digest_generated"]})
    assert r.status_code == 200
    wid = r.json()["id"]

    r = client.get("/api/webhooks")
    assert any(w["id"] == wid for w in r.json())

    r = client.patch(f"/api/webhooks/{wid}", json={"enabled": False})
    assert r.status_code == 200
    assert not next(w for w in client.get("/api/webhooks").json() if w["id"] == wid)["enabled"]

    r = client.delete(f"/api/webhooks/{wid}")
    assert r.status_code == 200
    assert not any(w["id"] == wid for w in client.get("/api/webhooks").json())


def test_webhook_rejects_unknown_event_type(client):
    r = client.post("/api/webhooks", json={"url": "http://x", "event_types": ["not_a_real_event"]})
    assert r.status_code == 422


def test_webhook_dispatch_fires_for_matching_event_only(client, monkeypatch):
    import asyncio
    calls = []

    async def fake_post(self, url, json=None, **kwargs):
        calls.append((url, json))

        class R:
            status_code = 200

        return R()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    client.post("/api/webhooks", json={"url": "http://a", "event_types": ["digest_generated"]})
    client.post("/api/webhooks", json={"url": "http://b", "event_types": ["urgent_email"]})

    from app.services import events
    asyncio.run(events.emit("digest_generated", {"files_changed": 2}))

    assert len(calls) == 1
    assert calls[0][0] == "http://a"
    assert calls[0][1]["event"] == "digest_generated"
    assert calls[0][1]["data"]["files_changed"] == 2


def test_automation_rule_crud(client):
    r = client.post("/api/automation/rules", json={
        "name": "notify on digest", "trigger_type": "digest_generated",
        "trigger_config": {}, "action_type": "webhook", "action_config": {"url": "http://x"},
    })
    assert r.status_code == 200
    rid = r.json()["id"]

    r = client.get("/api/automation/rules")
    assert any(rule["id"] == rid for rule in r.json())

    r = client.patch(f"/api/automation/rules/{rid}", json={"enabled": False})
    assert r.status_code == 200

    r = client.delete(f"/api/automation/rules/{rid}")
    assert r.status_code == 200
    assert not any(rule["id"] == rid for rule in client.get("/api/automation/rules").json())


def test_automation_rule_rejects_bad_action_config(client):
    r = client.post("/api/automation/rules", json={
        "name": "broken", "trigger_type": "digest_generated",
        "trigger_config": {}, "action_type": "webhook", "action_config": {},
    })
    assert r.status_code == 422

    r = client.post("/api/automation/rules", json={
        "name": "broken2", "trigger_type": "digest_generated",
        "trigger_config": {}, "action_type": "prompt", "action_config": {},
    })
    assert r.status_code == 422


def test_automation_rule_fires_webhook_action_on_matching_event(client, monkeypatch):
    import asyncio
    calls = []

    async def fake_post(self, url, json=None, **kwargs):
        calls.append((url, json))

        class R:
            status_code = 200

        return R()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    client.post("/api/automation/rules", json={
        "name": "notify", "trigger_type": "urgent_email",
        "trigger_config": {}, "action_type": "webhook", "action_config": {"url": "http://notify"},
    })

    from app.services import events
    asyncio.run(events.emit("urgent_email", {"subject": "Sign this today"}))

    assert any(c[0] == "http://notify" for c in calls)

    rules = client.get("/api/automation/rules").json()
    assert rules[0]["last_fired_at"] is not None


def test_todo_kanban_status_defaults_and_updates(client):
    r = client.post("/api/todos", json={"text": "write tests"})
    assert r.status_code == 200
    tid = r.json()["id"]
    assert r.json()["status"] == "todo"

    r = client.patch(f"/api/todos/{tid}", json={"status": "in_progress"})
    assert r.status_code == 200

    todos = client.get("/api/todos").json()
    match = next(t for t in todos if t["id"] == tid)
    assert match["status"] == "in_progress"
    assert match["done"] == 0

    r = client.patch(f"/api/todos/{tid}", json={"status": "done"})
    assert r.status_code == 200
    match = next(t for t in client.get("/api/todos").json() if t["id"] == tid)
    assert match["status"] == "done"
    assert match["done"] == 1


def test_todo_rejects_invalid_status(client):
    r = client.post("/api/todos", json={"text": "x", "status": "bogus"})
    assert r.status_code == 422


def test_automation_rule_folder_filter_only_fires_for_matching_folder(client, monkeypatch):
    import asyncio
    calls = []

    async def fake_post(self, url, json=None, **kwargs):
        calls.append(url)

        class R:
            status_code = 200

        return R()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    client.post("/api/automation/rules", json={
        "name": "inbox only", "trigger_type": "folder_file_added",
        "trigger_config": {"folder_id": "folder-a"}, "action_type": "webhook",
        "action_config": {"url": "http://inbox"},
    })

    from app.services import events
    asyncio.run(events.emit("folder_file_added", {"folder_id": "folder-b", "files": ["x"]}))
    assert calls == []

    asyncio.run(events.emit("folder_file_added", {"folder_id": "folder-a", "files": ["x"]}))
    assert calls == ["http://inbox"]
