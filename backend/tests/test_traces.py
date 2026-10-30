"""Per-turn traces recorded from real /api/chat turns (chat + agent)."""
from __future__ import annotations

import json

import pytest


def _stream(client, payload):
    events = []
    with client.stream("POST", "/api/chat", json=payload) as res:
        for line in res.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    return events


@pytest.fixture
def conv(fake_ollama, client):
    from app.core.config import settings
    from app.db import storage

    settings.update({"memory_enabled": False, "recall_enabled": False, "folder_recall_enabled": False,
                     "notes_todos_context_enabled": False})
    return storage.create_conversation("traced")["id"]


def test_chat_turn_is_traced(client, fake_ollama, conv):
    fake_ollama.queue("Traced reply here.")
    events = _stream(client, {"conversation_id": conv, "message": "hello, tell me something nice"})
    assert events[-1]["type"] == "done"
    traces = client.get(f"/api/traces?conversation_id={conv}").json()
    assert len(traces) == 1
    t = traces[0]
    assert t["mode"] == "chat" and t["status"] == "ok"
    assert t["model"] == "llama3.2:3b" and t["reason"]
    assert t["token_count"] >= 3 and t["first_token_ms"] is not None and t["total_ms"] >= t["first_token_ms"]
    assert client.get(f"/api/traces/{t['id']}").json()["id"] == t["id"]


def test_agent_turn_trace_lists_tool_calls(client, fake_ollama, conv, tmp_path):
    from app.core.config import settings
    from app.db import storage

    (tmp_path / "a.txt").write_text("x")
    storage.set_conversation_workdir(conv, str(tmp_path))
    settings.update({"agent_enabled": True, "agent_mode": "full", "agent_sandbox": "off"})
    fake_ollama.tool("read_file", path="a.txt").tool("read_file", path="missing").final("done")
    events = _stream(client, {"conversation_id": conv, "message": "read it", "agent_mode_on": True})
    assert events[-1]["type"] == "done"
    t = client.get(f"/api/traces?conversation_id={conv}").json()[0]
    assert t["mode"] == "agent"
    assert [(c["tool"], c["status"], c["ok"]) for c in t["tool_calls"]] == [
        ("read_file", "executed", True), ("read_file", "executed", False)]


def test_failed_turn_is_traced_as_error(client, fake_ollama, conv):
    from app.services.ollama_client import OllamaError

    fake_ollama.models = ["llama3.2:3b"]  # no fallback model available
    fake_ollama.queue(OllamaError("boom"))
    events = _stream(client, {"conversation_id": conv, "message": "this will fail"})
    assert events[-1]["type"] == "error"
    t = client.get(f"/api/traces?conversation_id={conv}").json()[0]
    assert t["status"] == "error" and "boom" in t["error"]


def test_prune_drops_old_traces(client, fake_ollama, conv):
    from app.db.storage import _conn
    from app.services import trace_service

    fake_ollama.queue("hi")
    _stream(client, {"conversation_id": conv, "message": "hello there"})
    with _conn() as c:
        c.execute("UPDATE turn_traces SET created_at = 0")
    assert trace_service.prune(30) == 1
    assert trace_service.list_traces(conv) == []
