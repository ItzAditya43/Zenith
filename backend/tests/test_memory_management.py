"""Memory management: scopes, provenance, approval of uncertain/sensitive
facts, exclusions, the browser's edit/merge/export, and per-reply citations."""
from __future__ import annotations

import json


def test_scopes_decide_where_a_memory_is_used(fake_ollama):
    from app.db import storage
    from app.services import memory_service as ms

    a = storage.create_conversation("a")
    b = storage.create_conversation("b")
    ms.add_memory("Likes green tea")
    ms.add_memory("Project uses Postgres", project_id="p1")
    ms.add_memory("Call the cat Miso in this story", scope="conversation", scope_conversation_id=a["id"])
    text_a, used_a = ms.memory_context(None, None, a["id"])
    text_b, _ = ms.memory_context("p1", None, b["id"])
    assert "green tea" in text_a and "Miso" in text_a and "Postgres" not in text_a
    assert "Postgres" in text_b and "Miso" not in text_b
    assert {m["content"] for m in used_a} == {"Likes green tea", "Call the cat Miso in this story"}
    assert ms.get_memory(used_a[0]["id"])["use_count"] == 1


async def test_uncertain_or_sensitive_facts_wait_for_approval(fake_ollama, client):
    from app.db import storage
    from app.services import memory_service as ms

    c = storage.create_conversation("x")
    msg = storage.add_message(c["id"], "user", "I use Arch Linux and I think I might move to Lisbon, also I'm diabetic")
    fake_ollama.queue(json.dumps([
        {"fact": "Uses Arch Linux", "confidence": 0.95, "sensitive": False},
        {"fact": "Might move to Lisbon", "confidence": 0.3, "sensitive": False},
        {"fact": "Is diabetic", "confidence": 0.9, "sensitive": True},
    ]))
    added = await ms.extract_from_text(msg["content"], c["id"])
    by = {m["content"]: m for m in added}
    assert by["Uses Arch Linux"]["status"] == "active"
    assert by["Might move to Lisbon"]["status"] == "pending"
    assert by["Is diabetic"]["status"] == "pending"
    assert all(m["source_message_id"] == msg["id"] for m in added)
    text, _ = ms.memory_context(None, None, c["id"])
    assert "Arch" in text and "Lisbon" not in text and "diabetic" not in text

    pending = client.get("/api/memories/browse?status=pending").json()
    assert len(pending) == 2 and pending[0]["source_title"] == "x"
    r = client.patch(f"/api/memories/{by['Is diabetic']['id']}", json={"status": "active"})
    assert r.status_code == 200
    assert "diabetic" in ms.memory_context(None, None, c["id"])[0]


async def test_exclusions_are_never_saved(fake_ollama):
    from app.core.config import settings
    from app.services import memory_service as ms

    settings.update({"memory_exclusions": ["salary", "password"]})
    try:
        fake_ollama.queue(json.dumps(["Earns a salary of 90k", "Prefers dark mode"]))
        added = await ms.extract_from_text("My salary is 90k and I prefer dark mode always")
        assert [m["content"] for m in added] == ["Prefers dark mode"]
        assert ms.add_memory("My password is hunter2") is None
    finally:
        settings.update({"memory_exclusions": []})


def test_edit_scope_merge_and_export(client):
    from app.db import storage

    c = storage.create_conversation("chat")
    a = client.post("/api/memories", json={"content": "Uses zsh"}).json()
    b = client.post("/api/memories", json={"content": "Shell is zsh with oh-my-zsh"}).json()
    assert client.patch(f"/api/memories/{a['id']}", json={"content": "Shell is zsh with oh-my-zsh"}).status_code == 400
    r = client.patch(f"/api/memories/{a['id']}", json={"scope": "conversation", "conversation_id": c["id"]}).json()
    assert r["scope"] == "conversation" and r["scope_conversation_id"] == c["id"]
    assert client.patch(f"/api/memories/{a['id']}", json={"scope": "project"}).status_code == 400

    merged = client.post("/api/memories/merge", json={"ids": [a["id"], b["id"]], "content": "Uses zsh with oh-my-zsh"}).json()
    assert merged["scope"] == "global"  # widest of the two
    rows = client.get("/api/memories/browse?q=zsh").json()
    assert [m["content"] for m in rows] == ["Uses zsh with oh-my-zsh"]
    exported = client.get("/api/memories/export")
    assert "attachment" in exported.headers["content-disposition"]
    assert exported.json()[0]["content"] == "Uses zsh with oh-my-zsh"


async def test_replies_cite_the_memories_they_used(fake_ollama):
    from app.db import storage
    from app.services import memory_service as ms
    from app.services.orchestrator import _build_system_context

    c = storage.create_conversation("c")
    ms.add_memory("Allergic to peanuts")
    _system, citations = await _build_system_context(c["id"], "suggest a snack for me please")
    mem = [x for x in citations if x["kind"] == "memory"]
    assert mem and mem[0]["text"] == "Allergic to peanuts"
