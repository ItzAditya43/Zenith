"""Bulk chat organisation: pin, tag, archive and delete many at once."""
from __future__ import annotations


def test_bulk_actions(client):
    from app.db import storage

    ids = [storage.create_conversation(f"c{i}")["id"] for i in range(3)]
    assert client.post("/api/conversations/bulk", json={"ids": ids[:2], "action": "pin"}).json()["count"] == 2
    client.post("/api/conversations/bulk", json={"ids": ids, "action": "tag", "tag": "work"})
    client.post("/api/conversations/bulk", json={"ids": ids[:1], "action": "untag", "tag": "work"})
    client.post("/api/conversations/bulk", json={"ids": ids[2:], "action": "archive"})
    by = {c["id"]: c for c in client.get("/api/conversations").json()}
    assert by[ids[0]]["pinned"] and not by[ids[2]]["pinned"]
    assert by[ids[0]]["tags"] == [] and by[ids[1]]["tags"] == ["work"]
    assert by[ids[2]]["archived"] is True and by[ids[1]]["archived"] is False
    assert client.post("/api/conversations/bulk", json={"ids": ids, "action": "tag"}).status_code == 400
    assert client.post("/api/conversations/bulk", json={"ids": ids, "action": "explode"}).status_code == 400
    client.post("/api/conversations/bulk", json={"ids": ids[1:], "action": "delete"})
    assert [c["id"] for c in client.get("/api/conversations").json()] == [ids[0]]
