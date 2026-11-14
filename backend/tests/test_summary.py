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
