from __future__ import annotations

from app.db import storage


def test_search_filters(client):
    a = storage.create_conversation("A")
    b = storage.create_conversation("B")
    storage.add_message(a["id"], "user", "tell me about tomatoes")
    storage.add_message(b["id"], "assistant", "tomatoes are fruit", model="llama3.2:3b")
    ids = lambda q: {r["conversation_id"] for r in storage.search_conversations(q)}  # noqa: E731
    assert ids("tomatoes") == {a["id"], b["id"]}
    assert ids("tomatoes from:me") == {a["id"]}
    assert ids("tomatoes model:llama") == {b["id"]}
    assert ids("from:zenith") == {b["id"]}
    assert ids("tomatoes after:2999-01-01") == set()
    assert storage.search_all("from:me")["memories"] == []
