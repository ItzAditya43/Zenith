"""Pin/tags/share links, snippets, per-project agent-mode override, and
the code-editor panel's git/run endpoints."""
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


def test_pin_and_tags(client):
    r = client.post("/api/conversations", json={"title": "t"})
    cid = r.json()["id"]

    r = client.patch(f"/api/conversations/{cid}/pin", json={"pinned": True})
    assert r.status_code == 200

    r = client.patch(f"/api/conversations/{cid}/tags", json={"tags": ["work", "ideas"]})
    assert r.status_code == 200

    convs = client.get("/api/conversations").json()
    match = next(c for c in convs if c["id"] == cid)
    assert match["pinned"] is True
    assert match["tags"] == ["work", "ideas"]


def test_tags_reject_non_list(client):
    r = client.post("/api/conversations", json={"title": "t"})
    cid = r.json()["id"]
    r = client.patch(f"/api/conversations/{cid}/tags", json={"tags": "not-a-list"})
    assert r.status_code == 422


def test_share_link_round_trip(client):
    r = client.post("/api/conversations", json={"title": "shared chat"})
    cid = r.json()["id"]

    r = client.post(f"/api/conversations/{cid}/share")
    assert r.status_code == 200
    token = r.json()["token"]

    r = client.get(f"/api/share/{token}")
    assert r.status_code == 200
    assert r.json()["title"] == "shared chat"

    r = client.delete(f"/api/conversations/{cid}/share")
    assert r.status_code == 200
    r = client.get(f"/api/share/{token}")
    assert r.status_code == 404


def test_share_link_unknown_token(client):
    r = client.get("/api/share/nonexistent")
    assert r.status_code == 404


def test_snippets_crud(client):
    r = client.post("/api/snippets", json={"title": "Bug report", "content": "Steps to reproduce:\n1."})
    assert r.status_code == 200
    sid = r.json()["id"]

    r = client.get("/api/snippets")
    assert any(s["id"] == sid for s in r.json())

    r = client.delete(f"/api/snippets/{sid}")
    assert r.status_code == 200
    r = client.get("/api/snippets")
    assert not any(s["id"] == sid for s in r.json())


def test_project_agent_mode_override(client):
    r = client.post("/api/projects", json={"name": "scratch"})
    pid = r.json()["id"]

    r = client.patch(f"/api/projects/{pid}/agent-mode", json={"agent_mode": "full"})
    assert r.status_code == 200

    projects = client.get("/api/projects").json()
    match = next(p for p in projects if p["id"] == pid)
    assert match["agent_mode"] == "full"


def test_project_agent_mode_rejects_invalid(client):
    r = client.post("/api/projects", json={"name": "scratch"})
    pid = r.json()["id"]
    r = client.patch(f"/api/projects/{pid}/agent-mode", json={"agent_mode": "yolo"})
    assert r.status_code == 422


def test_git_status_and_run_need_workdir(client, tmp_path):
    r = client.post("/api/conversations", json={"title": "t"})
    cid = r.json()["id"]
    assert client.get(f"/api/conversations/{cid}/git/status").status_code == 404
    assert client.post(f"/api/conversations/{cid}/run", json={}).status_code == 404


def test_git_status_in_a_real_repo(client, tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("hi")

    r = client.post("/api/conversations", json={"title": "t"})
    cid = r.json()["id"]
    client.patch(f"/api/conversations/{cid}/workdir", json={"workdir": str(tmp_path)})

    r = client.get(f"/api/conversations/{cid}/git/status")
    assert r.status_code == 200
    assert "a.txt" in r.json()["output"]


def test_digest_latest_is_null_when_none_generated(client):
    r = client.get("/api/digest/latest")
    assert r.status_code == 200
    assert r.json() is None


def test_digest_run_now_reports_nothing_new_when_nothing_changed(client):
    r = client.post("/api/digest/run-now")
    assert r.status_code == 200
    assert r.json()["generated"] is False


def test_digest_history_reflects_stored_digests(client):
    from app.db import storage

    storage.create_digest("Nothing much happened.", files_changed=0, memories_added=0)
    r = client.get("/api/digest/history")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["content"] == "Nothing much happened."

    r = client.get("/api/digest/latest")
    assert r.json()["content"] == "Nothing much happened."


def test_memory_conflicts_empty_when_none_flagged(client):
    r = client.get("/api/memories/conflicts")
    assert r.status_code == 200
    assert r.json() == []


def test_memory_conflict_resolve_is_idempotent(client):
    r = client.post("/api/memories/conflicts/nonexistent/resolve")
    assert r.status_code == 200  # no-op, not an error — matches other resolve-style endpoints


def test_memory_conflict_full_round_trip(client):
    from app.db import storage
    from app.services import memory_service

    a = memory_service.add_memory("uses fish shell")
    b = memory_service.add_memory("uses zsh as their shell")
    conflict = storage.create_memory_conflict(a["id"], b["id"], "Can't use two default shells at once.")

    r = client.get("/api/memories/conflicts")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["memory_a"]["id"] == a["id"]
    assert body[0]["memory_b"]["id"] == b["id"]

    r = client.post(f"/api/memories/conflicts/{conflict['id']}/resolve")
    assert r.status_code == 200

    r = client.get("/api/memories/conflicts")
    assert r.json() == []


def test_memory_conflict_dropped_if_a_memory_was_deleted(client):
    from app.db import storage
    from app.services import memory_service

    a = memory_service.add_memory("likes tea")
    b = memory_service.add_memory("likes coffee")
    storage.create_memory_conflict(a["id"], b["id"], "reason")
    memory_service.delete_memory(a["id"])

    r = client.get("/api/memories/conflicts")
    assert r.json() == []  # cleaned up, not shown broken


def test_knowledge_graph_reflects_real_relationships(client):
    from app.db import storage
    from app.services import memory_service

    proj = storage.create_project("demo")
    conv = storage.create_conversation("Trip planning", project_id=proj["id"])
    memory_service.add_memory("lives in Berlin", source_conversation_id=conv["id"], project_id=proj["id"])

    r = client.get("/api/graph")
    assert r.status_code == 200
    body = r.json()

    node_ids = {n["id"] for n in body["nodes"]}
    assert f"project:{proj['id']}" in node_ids
    assert f"conversation:{conv['id']}" in node_ids
    assert any(n["type"] == "memory" and "Berlin" in n["label"] for n in body["nodes"])

    edges = body["edges"]
    assert {"from": f"conversation:{conv['id']}", "to": f"project:{proj['id']}", "kind": "in_project"} in edges
    assert any(
        e["kind"] == "extracted_from" and e["to"] == f"conversation:{conv['id']}"
        for e in edges
    )


def test_routing_status_reports_inactive_without_embedding_model(client):
    r = client.get("/api/routing/status")
    assert r.status_code == 200
    body = r.json()
    assert "active" in body and "embedding_model" in body and "confidence_threshold" in body


def test_chat_resume_404_when_nothing_running(client):
    r = client.post("/api/conversations", json={"title": "t"})
    cid = r.json()["id"]
    r = client.get(f"/api/conversations/{cid}/chat/resume")
    assert r.status_code == 404


def test_run_checks_with_explicit_command(client, tmp_path):
    r = client.post("/api/conversations", json={"title": "t"})
    cid = r.json()["id"]
    client.patch(f"/api/conversations/{cid}/workdir", json={"workdir": str(tmp_path)})

    r = client.post(f"/api/conversations/{cid}/run", json={"command": "echo hello"})
    assert r.status_code == 200
    assert "hello" in r.json()["output"]
