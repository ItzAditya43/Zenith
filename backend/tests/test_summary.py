"""Long chats: messages that leave the context window are folded into a summary."""
from __future__ import annotations

import pytest


@pytest.fixture
def long_chat(fake_ollama):
    from app.core.config import settings
    from app.db import storage

    settings.update({"max_context_messages": 4, "summarize_long_chats": True, "model_overrides": {"general": None}})
    c = storage.create_conversation("long")
    parent = None
    for i in range(12):
        role = "user" if i % 2 == 0 else "assistant"
        m = storage.add_message(c["id"], role, f"message {i} about the {'database schema' if i < 2 else 'ui'}", parent_id=parent)
        parent = m["id"]
    yield c["id"], fake_ollama
    settings.update({"max_context_messages": 24})


async def test_dropped_messages_are_summarised_and_used(long_chat):
    from app.db import storage
    from app.services import summary_service

    cid, fake = long_chat
    history = storage.get_messages(cid)
    assert summary_service.summary_block(cid, history) == ""

    fake.queue("- User is designing the database schema\n- Then moved on to the UI")
    assert await summary_service.update(cid) is True
    prompt = fake.calls[-1]["messages"][0]["content"]
    assert "message 0 about the database schema" in prompt and "message 7" in prompt
    assert "message 8" not in prompt  # still inside the window: not summarised

    block = summary_service.summary_block(cid, history)
    assert "designing the database schema" in block and "no longer shown in full" in block


async def test_no_new_batch_means_no_new_call(long_chat):
    from app.services import summary_service

    cid, fake = long_chat
    fake.queue("- first summary")
    await summary_service.update(cid)
    calls = len(fake.calls)
    assert await summary_service.update(cid) is False
    assert len(fake.calls) == calls


async def test_summary_of_another_branch_is_ignored(long_chat):
    from app.db import storage
    from app.services import summary_service

    cid, fake = long_chat
    fake.queue("- old branch summary")
    await summary_service.update(cid)
    history = storage.get_messages(cid)
    # Drop the last covered message from what's "active" (as an edit/branch switch would).
    covered = summary_service._load(cid)["covered_until"]
    changed = [m for m in history if m["id"] != covered]
    assert summary_service.summary_block(cid, changed) == ""


async def test_summary_reaches_the_model_on_the_next_turn(long_chat):
    from app.services import summary_service
    from app.services.orchestrator import _build_system_context

    cid, fake = long_chat
    fake.queue("- The user picked SQLite for storage")
    await summary_service.update(cid)
    system, _ = await _build_system_context(cid, "what did we pick for storage?")
    assert "picked SQLite" in system


async def test_can_be_turned_off(long_chat):
    from app.core.config import settings
    from app.services import summary_service

    cid, _ = long_chat
    settings.update({"summarize_long_chats": False})
    try:
        assert await summary_service.update(cid) is False
    finally:
        settings.update({"summarize_long_chats": True})


async def test_structured_state_with_sources(long_chat):
    import json

    from app.db import storage
    from app.services import summary_service

    cid, fake = long_chat
    fake.queue(json.dumps({
        "goals": [{"text": "Design the database schema", "sources": ["m1"]}],
        "decisions": [{"text": "Use SQLite", "sources": ["m2", "m99"]}],
        "next_actions": ["Build the UI"],
    }))
    assert await summary_service.update(cid) is True
    ids = [m["id"] for m in storage.get_messages(cid)]
    st = summary_service.inspect(cid)
    assert st["current"] and st["covered_count"] == 8
    assert st["state"]["goals"][0]["sources"] == [ids[0]]
    assert st["state"]["decisions"][0]["sources"] == [ids[1]]  # unknown m99 dropped
    block = summary_service.summary_block(cid, storage.get_messages(cid))
    assert "Decisions:" in block and "- Use SQLite" in block


async def test_pinned_items_survive_regenerate_and_edits(long_chat, client):
    import json

    from app.db import storage
    from app.services import summary_service

    cid, fake = long_chat
    fake.queue(json.dumps({"facts": [{"text": "Old fact", "sources": ["m1"]}]}))
    await summary_service.update(cid)
    st = client.get(f"/api/conversations/{cid}/state").json()
    st["state"]["constraints"] = [{"text": "Never use MongoDB", "pinned": True}]
    r = client.put(f"/api/conversations/{cid}/state", json={"state": st["state"]})
    assert r.status_code == 200 and r.json()["edited_at"]

    fake.queue(json.dumps({"facts": [{"text": "New fact", "sources": ["m3"]}], "constraints": []}))
    r = client.post(f"/api/conversations/{cid}/state/regenerate").json()
    assert r["regenerated"] is True
    assert [i["text"] for i in r["state"]["constraints"]] == ["Never use MongoDB"]
    assert r["state"]["facts"][0]["text"] == "New fact"

    # After an edit/branch switch makes the state stale, pins still reach the model.
    history = storage.get_messages(cid)
    covered = summary_service._load(cid)["covered_until"]
    block = summary_service.summary_block(cid, [m for m in history if m["id"] != covered])
    assert "Never use MongoDB" in block and "New fact" not in block


async def test_clear_state(long_chat, client):
    cid, fake = long_chat
    fake.queue("- something")
    from app.services import summary_service

    await summary_service.update(cid)
    assert client.delete(f"/api/conversations/{cid}/state").json()["ok"]
    assert client.get(f"/api/conversations/{cid}/state").json()["exists"] is False
