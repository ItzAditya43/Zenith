"""orchestrator.run_turn — the plain chat path: routing, attachments,
RAG over documents, web context, system context (persona, memories,
recall, notes/to-dos) and branching — against the scripted fake Ollama."""
from __future__ import annotations

import pytest


@pytest.fixture
def chat(fake_ollama):
    from app.core.config import settings
    from app.db import storage

    settings.update({
        "memory_enabled": True, "recall_enabled": True, "folder_recall_enabled": False,
        "notes_todos_context_enabled": True, "system_prompt": "", "rag_enabled": True,
        "rag_embedding_model": "nomic-embed-text", "rag_rerank_enabled": False,
        "web_fetch_max_urls_per_turn": 3,
    })
    conv = storage.create_conversation("chat test")
    return {"conv": conv["id"], "fake": fake_ollama}


async def _turn(conv, text, **kw):
    from app.services import orchestrator

    decision, stream, sources, parent_id = await orchestrator.run_turn(conv, text, kw.pop("attachments", []), **kw)
    reply = "".join([piece async for piece in stream])
    return decision, reply, sources, parent_id


def _last_call(fake):
    return fake.calls[-1]["messages"]


def _upload(name: str, text: str, conv: str) -> str:
    from app.services import attachments, rag_service

    att = attachments.save_upload(name, text.encode(), conversation_id=conv)
    rag_service.index_document(att.id, text, conv)
    return att.id


# --- routing + persistence ------------------------------------------------------


async def test_plain_turn_routes_streams_and_persists(chat):
    from app.db import storage

    chat["fake"].queue("Hello there!")
    decision, reply, _, parent_id = await _turn(chat["conv"], "hi, how are you today?")
    assert reply == "Hello there!"
    assert decision.model == "llama3.2:3b" and decision.role in ("general", "small_fast")
    user_msgs = [m for m in storage.get_messages(chat["conv"]) if m["role"] == "user"]
    assert user_msgs[-1]["id"] == parent_id and user_msgs[-1]["content"] == "hi, how are you today?"


async def test_code_question_routes_to_coder_model(chat):
    decision, *_ = await _turn(chat["conv"], "def fib(n): fix this python function please")
    assert decision.role == "code" and decision.model == "qwen2.5-coder:7b"


async def test_manual_override_is_used_and_logged_as_routing_signal(chat):
    from app.db import storage

    decision, *_ = await _turn(chat["conv"], "def f(): pass  # review", model_override="llama3.2:3b")
    assert decision.model == "llama3.2:3b" and decision.confidence == 1.0
    summary = storage.routing_override_summary()
    assert summary and summary[0]["override_model"] == "llama3.2:3b"
    assert chat["fake"].calls[-1]["model"] == "llama3.2:3b"


async def test_history_is_trimmed_to_max_context_messages(chat):
    from app.core.config import settings
    from app.db import storage

    settings.update({"max_context_messages": 4})
    parent = None
    for i in range(10):
        parent = storage.add_message(chat["conv"], "user" if i % 2 == 0 else "assistant", f"m{i}", parent_id=parent)["id"]
    await _turn(chat["conv"], "latest question here")
    non_system = [m for m in _last_call(chat["fake"]) if m["role"] != "system"]
    assert [m["content"] for m in non_system] == ["m6", "m7", "m8", "m9", "latest question here"]


# --- documents ----------------------------------------------------------------------


async def test_document_is_answered_from_retrieved_chunks(chat):
    aid = _upload("report.txt", "The launch date moved to March 14 because of supplier delays.", chat["conv"])
    _, _, sources, _ = await _turn(chat["conv"], "When is the launch date?", attachments=[aid])
    user = _last_call(chat["fake"])[-1]["content"]
    assert "[From 'report.txt']" in user and "March 14" in user
    assert any(s.get("kind") == "document" and s.get("attachment_id") == aid for s in sources)


async def test_two_documents_both_reach_the_model(chat):
    """Regression: retrieval used to overwrite the message per document."""
    a = _upload("alpha.txt", "Alpha project budget is 40k dollars.", chat["conv"])
    b = _upload("beta.txt", "Beta project budget is 75k dollars.", chat["conv"])
    await _turn(chat["conv"], "Compare the project budget in both files", attachments=[a, b])
    user = _last_call(chat["fake"])[-1]["content"]
    assert "[From 'alpha.txt']" in user and "[From 'beta.txt']" in user
    assert "40k" in user and "75k" in user


async def test_unindexed_document_keeps_its_full_text(chat):
    from app.services import attachments

    indexed = _upload("indexed.txt", "Indexed content about penguins.", chat["conv"])
    raw = attachments.save_upload("raw.txt", b"Fresh upload about walruses.", conversation_id=chat["conv"]).id
    await _turn(chat["conv"], "Tell me about penguins and walruses", attachments=[indexed, raw])
    user = _last_call(chat["fake"])[-1]["content"]
    assert "Indexed content about penguins" in user and "Fresh upload about walruses" in user


async def test_document_and_web_context_are_both_kept(chat, monkeypatch):
    """Regression: document retrieval used to wipe web context."""
    from app.services import web_service

    async def search(q, max_results=None):
        return [{"url": "https://example.com/a", "title": "A", "snippet": "web snippet"}]

    async def fetch(url):
        return {"url": url, "title": "Example A", "text": "Fresh web fact about the launch."}

    monkeypatch.setattr(web_service, "search", search)
    monkeypatch.setattr(web_service, "fetch_url", fetch)
    aid = _upload("plan.txt", "Internal plan says launch in Q2.", chat["conv"])
    _, _, sources, _ = await _turn(chat["conv"], "What do we know about the launch?", attachments=[aid], web_search=True)
    user = _last_call(chat["fake"])[-1]["content"]
    assert "Internal plan says launch in Q2" in user
    assert "Fresh web fact about the launch" in user
    assert {"url": "https://example.com/a", "title": "Example A"} in sources


# --- web context honesty ------------------------------------------------------------


async def test_empty_web_search_tells_the_model(chat, monkeypatch):
    from app.services import web_service

    async def search(q, max_results=None):
        return []

    monkeypatch.setattr(web_service, "search", search)
    await _turn(chat["conv"], "latest news on fusion power", web_search=True)
    assert "web search was attempted" in _last_call(chat["fake"])[-1]["content"]


async def test_unfetchable_link_tells_the_model(chat, monkeypatch):
    from app.services import web_service

    async def fetch(url):
        raise OSError("connection refused")

    monkeypatch.setattr(web_service, "fetch_url", fetch)
    await _turn(chat["conv"], "summarise https://dead.example.invalid/page")
    assert "could not be fetched" in _last_call(chat["fake"])[-1]["content"]


async def test_failed_fetch_falls_back_to_search_snippet(chat, monkeypatch):
    from app.services import web_service

    async def search(q, max_results=None):
        return [{"url": "https://example.com/x", "title": "X", "snippet": "the snippet survives"}]

    async def fetch(url):
        return None

    monkeypatch.setattr(web_service, "search", search)
    monkeypatch.setattr(web_service, "fetch_url", fetch)
    await _turn(chat["conv"], "anything at all here", web_search=True)
    assert "the snippet survives" in _last_call(chat["fake"])[-1]["content"]


# --- system context -------------------------------------------------------------------


async def test_system_prompt_memories_notes_and_todos(chat):
    from app.core.config import settings
    from app.db import storage
    from app.services.memory_service import add_memory

    settings.update({"system_prompt": "Answer like a pirate."})
    add_memory("Lives in Lisbon")
    storage.create_note("Buy more coffee filters")
    storage.create_todo("Renew passport")
    await _turn(chat["conv"], "what should I do this weekend?")
    system = _last_call(chat["fake"])[0]
    assert system["role"] == "system"
    for expected in ("Answer like a pirate.", "Lives in Lisbon", "Buy more coffee filters", "Renew passport"):
        assert expected in system["content"]


async def test_persona_replaces_global_system_prompt(chat):
    from app.core.config import settings
    from app.services import persona_service

    settings.update({"system_prompt": "GLOBAL PROMPT"})
    persona = persona_service.create_persona("Critic", "You are a harsh film critic.")
    persona_service.set_conversation_persona(chat["conv"], persona["id"])
    await _turn(chat["conv"], "review the movie Up")
    system = _last_call(chat["fake"])[0]["content"]
    assert "harsh film critic" in system and "GLOBAL PROMPT" not in system


async def test_recall_pulls_from_other_conversations_only(chat):
    from app.db import storage
    from app.services import rag_service

    other = storage.create_conversation("old")["id"]
    rag_service.index_message(other, "user", "My dog Biscuit is allergic to chicken")
    rag_service.index_message(chat["conv"], "user", "this conversation's own dog chicken message")
    _, _, sources, _ = await _turn(chat["conv"], "what food is my dog Biscuit allergic to?")
    system = _last_call(chat["fake"])[0]["content"]
    assert "Biscuit is allergic to chicken" in system
    assert "this conversation's own" not in system
    assert any(s["kind"] == "recall" for s in sources)


async def test_memory_disabled_keeps_memories_out(chat):
    from app.core.config import settings
    from app.services.memory_service import add_memory

    add_memory("Secret preference that should stay out")
    settings.update({"memory_enabled": False, "notes_todos_context_enabled": False, "recall_enabled": False})
    await _turn(chat["conv"], "hello hello hello")
    assert all("Secret preference" not in m["content"] for m in _last_call(chat["fake"]))


# --- branching ----------------------------------------------------------------------------


async def test_regenerate_reuses_the_user_message(chat):
    from app.db import storage

    _, _, _, parent_id = await _turn(chat["conv"], "tell me a joke")
    storage.add_message(chat["conv"], "assistant", "first joke", parent_id=parent_id)
    before = len(storage.get_messages(chat["conv"], active_only=False))
    _, _, _, regen_parent = await _turn(chat["conv"], "", regenerate_user_message_id=parent_id)
    assert regen_parent == parent_id
    assert len(storage.get_messages(chat["conv"], active_only=False)) == before
    assert _last_call(chat["fake"])[-1]["content"] == "tell me a joke"


async def test_regenerate_unknown_message_raises(chat):
    with pytest.raises(ValueError):
        await _turn(chat["conv"], "", regenerate_user_message_id="nope")


async def test_explicit_parent_creates_a_branch(chat):
    from app.db import storage

    _, _, _, first = await _turn(chat["conv"], "original question")
    _, _, _, edited = await _turn(chat["conv"], "edited question", parent_message_id=None, parent_explicit=True)
    assert storage.get_message(edited)["parent_id"] is None
    assert edited != first
