"""Readiness check and Get-started progress."""
from __future__ import annotations


def test_ready_with_local_model(client, fake_ollama):
    r = client.get("/api/setup/status").json()
    checks = {c["id"]: c for c in r["checks"]}
    assert r["ready_to_chat"] and checks["ollama"]["ok"] and checks["model"]["ok"]
    assert r["progress"] == {"chatted": False, "file": False, "research": False, "agent": False, "memory": False}
    assert r["hidden"] is False


def test_not_ready_explains_the_fix(client, fake_ollama, monkeypatch):
    from app.services import ollama_client

    async def down(self):
        raise ollama_client.OllamaError("down")

    monkeypatch.setattr(ollama_client.OllamaClient, "_ollama_models", down)
    r = client.get("/api/setup/status").json()
    checks = {c["id"]: c for c in r["checks"]}
    assert not r["ready_to_chat"] and not checks["ollama"]["ok"] and checks["ollama"]["fix"]
    assert "API provider" in checks["ollama"]["why"]

    client.post("/api/providers", json={"id": "groq", "base_url": "https://api.groq.com/openai/v1", "api_key": "k"})
    r = client.get("/api/setup/status").json()
    assert r["ready_to_chat"] and {c["id"]: c for c in r["checks"]}["ollama"]["optional"] is True


def test_progress_and_hide(client, fake_ollama):
    from app.db import storage

    c = storage.create_conversation("x")
    storage.add_message(c["id"], "assistant", "hi")
    assert client.get("/api/setup/status").json()["progress"]["chatted"] is True
    client.patch("/api/config", json={"setup_checklist_hidden": True})
    assert client.get("/api/setup/status").json()["hidden"] is True
