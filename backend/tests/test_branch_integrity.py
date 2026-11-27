from __future__ import annotations

from app.db import storage
from app.db.storage import _conn


def test_detect_and_repair(client):
    c = storage.create_conversation("x")
    a = storage.add_message(c["id"], "user", "q")
    b = storage.add_message(c["id"], "assistant", "r1", parent_id=a["id"])
    assert client.get(f"/api/conversations/{c['id']}/integrity").json()["ok"] is True
    b2 = storage.add_message(c["id"], "assistant", "r2", parent_id=a["id"])
    orphan = storage.add_message(c["id"], "user", "lost", parent_id=b2["id"])
    with _conn() as conn:
        conn.execute("UPDATE messages SET active = 1 WHERE id IN (?, ?)", (b["id"], b2["id"]))
        conn.execute("UPDATE messages SET parent_id = 'gone' WHERE id = ?", (orphan["id"],))
    r = client.get(f"/api/conversations/{c['id']}/integrity").json()
    assert not r["ok"] and len(r["problems"]) >= 2
    r = client.get(f"/api/conversations/{c['id']}/integrity?repair=true").json()
    assert r["repaired"]
    assert client.get(f"/api/conversations/{c['id']}/integrity").json()["ok"] is True
