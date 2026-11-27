from __future__ import annotations

import io
import json

CHATGPT = [{"title": "Trip", "create_time": 1, "mapping": {
    "a": {"id": "a", "parent": None, "children": ["b"], "message": {"author": {"role": "user"}, "content": {"parts": ["hi"]}, "create_time": 1}},
    "b": {"id": "b", "parent": "a", "children": [], "message": {"author": {"role": "assistant"}, "content": {"parts": ["hello"]}, "create_time": 2}},
}}]


def _post(client, preview=False):
    f = {"file": ("conversations.json", io.BytesIO(json.dumps(CHATGPT).encode()), "application/json")}
    return client.post("/api/import" + ("?preview=true" if preview else ""), files=f).json()


def test_preview_then_import_then_undo(client):
    pv = _post(client, preview=True)
    assert pv["conversations"] == 1 and pv["sample"][0]["title"] == "Trip"
    assert client.get("/api/conversations").json() == [] or all(c["title"] != "Trip" for c in client.get("/api/conversations").json())
    res = _post(client)
    assert res["conversations"] == 1 and res["batch_id"]
    assert _post(client, preview=True)["skipped_duplicates"] == 1
    b = client.get("/api/import/batches").json()
    assert b[0]["batch_id"] == res["batch_id"]
    assert client.delete(f"/api/import/batches/{res['batch_id']}").json()["deleted_conversations"] == 1
    assert all(c["title"] != "Trip" for c in client.get("/api/conversations").json())
    assert _post(client, preview=True)["conversations"] == 1  # can import again
