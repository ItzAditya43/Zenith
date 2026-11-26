"""Answer feedback (per-model totals, never applied automatically) and
timed, saved model comparisons."""
from __future__ import annotations

import json


def _events(resp):
    return [json.loads(line[5:]) for line in resp.iter_lines() if line.startswith("data:")]


def test_feedback_roundtrip_and_summary(client):
    from app.db import storage

    c = storage.create_conversation("c")
    u = storage.add_message(c["id"], "user", "hi")
    a = storage.add_message(c["id"], "assistant", "hello", model="llama3.2:3b", route_role="small_fast", parent_id=u["id"])
    b = storage.add_message(c["id"], "assistant", "yo", model="qwen2.5:7b", route_role="general", parent_id=u["id"])
    assert client.put(f"/api/messages/{u['id']}/feedback", json={"rating": 1}).status_code == 400
    assert client.put("/api/messages/nope/feedback", json={"rating": 1}).status_code == 404
    client.put(f"/api/messages/{a['id']}/feedback", json={"rating": -1})
    r = client.put(f"/api/messages/{a['id']}/feedback", json={"wrong_model": True, "note": "needed code model"}).json()
    assert r["rating"] == -1 and r["wrong_model"] == 1  # partial update keeps the rating
    client.put(f"/api/messages/{b['id']}/feedback", json={"rating": 1})
    assert set(client.get(f"/api/conversations/{c['id']}/feedback").json()) == {a["id"], b["id"]}
    s = client.get("/api/feedback/summary").json()
    by = {m["model"]: m for m in s["models"]}
    assert by["llama3.2:3b"]["down"] == 1 and by["llama3.2:3b"]["wrong_model"] == 1
    assert by["qwen2.5:7b"]["approval"] == 1.0
    assert s["wrong_model_recent"][0]["note"] == "needed code model"
    client.delete(f"/api/messages/{b['id']}/feedback")
    assert "qwen2.5:7b" not in {m["model"] for m in client.get("/api/feedback/summary").json()["models"]}


def test_compare_times_models_and_saves(fake_ollama, client):
    def responder(model, messages, fmt):
        if model == "broken:1b":
            raise RuntimeError("model not found")
        return f"answer from {model} with several words"

    fake_ollama.responder = responder
    with client.stream("POST", "/api/compare", json={"prompt": "hi", "models": ["llama3.2:3b", "qwen2.5-coder:7b", "broken:1b"]}) as r:
        ev = _events(r)
    done = {e["model"]: e for e in ev if e["type"] == "model_done"}
    assert set(done) == {"llama3.2:3b", "qwen2.5-coder:7b"}
    assert done["llama3.2:3b"]["text"] == "answer from llama3.2:3b with several words"
    assert done["llama3.2:3b"]["tokens"] > 1 and done["llama3.2:3b"]["ttft_ms"] is not None
    assert any(e["type"] == "model_error" and e["model"] == "broken:1b" for e in ev)
    cid = ev[-1]["id"]
    saved = client.get(f"/api/compare/{cid}").json()
    assert [x["model"] for x in saved["results"]] == ["llama3.2:3b", "qwen2.5-coder:7b", "broken:1b"]
    assert client.post(f"/api/compare/{cid}/winner", json={"model": "nope"}).status_code == 400
    assert client.post(f"/api/compare/{cid}/winner", json={"model": "llama3.2:3b"}).json()["ok"]
    assert client.get("/api/compare").json()[0]["winner"] == "llama3.2:3b"
    with client.stream("POST", "/api/compare", json={"prompt": "hi", "models": ["a", "a"]}) as r:
        assert _events(r)[0]["type"] == "error"
