"""Keep A/B, keep both, merge and dismiss — each undoable, nothing deleted."""
from __future__ import annotations

from app.db import storage
from app.services import memory_service


def _pair(a="uses fish shell", b="uses zsh"):
    ma = memory_service.add_memory(a)
    mb = memory_service.add_memory(b)
    c = storage.create_memory_conflict(ma["id"], mb["id"], "different shells")
    return ma, mb, c


def test_list_has_evidence_and_suggestion(client):
    _pair()
    rows = client.get("/api/memories/conflicts").json()
    assert len(rows) == 1
    assert rows[0]["suggestion"]["action"] in ("keep_a", "keep_b", "keep_both")
    assert "source_title" in rows[0]["memory_a"]


def test_keep_one_then_undo(client):
    ma, mb, c = _pair()
    r = client.post(f"/api/memories/conflicts/{c['id']}/resolve", json={"action": "keep_a"})
    assert r.status_code == 200
    assert memory_service.get_memory(mb["id"])["enabled"] == 0
    assert client.get("/api/memories/conflicts").json() == []
    assert client.get("/api/memories/conflicts/resolved").json()[0]["resolution"] == "keep_a"
    client.post(f"/api/memories/conflicts/{c['id']}/undo")
    assert memory_service.get_memory(mb["id"])["enabled"] == 1
    assert len(client.get("/api/memories/conflicts").json()) == 1


def test_merge_then_undo_restores_text(client):
    ma, mb, c = _pair("works at Acme", "works at Globex")
    assert client.post(f"/api/memories/conflicts/{c['id']}/resolve", json={"action": "merge"}).status_code == 400
    client.post(f"/api/memories/conflicts/{c['id']}/resolve", json={"action": "merge", "text": "moved from Acme to Globex in 2026"})
    assert memory_service.get_memory(ma["id"])["content"] == "moved from Acme to Globex in 2026"
    assert memory_service.get_memory(mb["id"])["enabled"] == 0
    client.post(f"/api/memories/conflicts/{c['id']}/undo")
    assert memory_service.get_memory(ma["id"])["content"] == "works at Acme"
    assert memory_service.get_memory(mb["id"])["enabled"] == 1


def test_dismiss_without_body_still_works(client):
    _, _, c = _pair("likes tea", "likes coffee")
    assert client.post(f"/api/memories/conflicts/{c['id']}/resolve").status_code == 200
    assert client.get("/api/memories/conflicts").json() == []
