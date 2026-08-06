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


def test_run_checks_with_explicit_command(client, tmp_path):
    r = client.post("/api/conversations", json={"title": "t"})
    cid = r.json()["id"]
    client.patch(f"/api/conversations/{cid}/workdir", json={"workdir": str(tmp_path)})

    r = client.post(f"/api/conversations/{cid}/run", json={"command": "echo hello"})
    assert r.status_code == 200
    assert "hello" in r.json()["output"]
