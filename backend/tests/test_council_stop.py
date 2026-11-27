from __future__ import annotations

import asyncio

from app.services import council_service


def test_member_timeout_and_stop(fake_ollama, monkeypatch):
    from app.db import storage
    from app.services import ollama_client

    async def slow_stream(self, model, messages, **kw):
        if model == "slow":
            await asyncio.sleep(30)
        yield f"answer from {model}"

    monkeypatch.setattr(ollama_client.OllamaClient, "chat_stream", slow_stream)
    monkeypatch.setattr(council_service, "OllamaClient", ollama_client.OllamaClient)
    monkeypatch.setattr(council_service, "_member_timeout", lambda: 0.3)
    conv = storage.create_conversation("c")

    async def go():
        return [e async for e in council_service.run_council(conv["id"], "hi", [], ["fast", "slow"])]

    evs = asyncio.run(go())
    errs = {e["model"]: e["message"] for e in evs if e["type"] == "council_error"}
    assert "slow" in errs and "longer than" in errs["slow"]
    done = {e["model"]: e["text"] for e in evs if e["type"] == "council_done"}
    assert done["fast"] == "answer from fast"
    assert council_service.cancel_member(conv["id"], "fast") is False
