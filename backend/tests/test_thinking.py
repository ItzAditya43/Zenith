"""Thinking models: the think flag, streamed reasoning, and 'done' not
waiting on post-reply work."""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_ollama(monkeypatch, capabilities, chunks, seen):
    from app.services import ollama_client

    ollama_client._CAPABILITIES_CACHE.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": capabilities})
        seen.append(body)
        lines = "".join(json.dumps(c) + "\n" for c in chunks) + json.dumps({"done": True}) + "\n"
        return httpx.Response(200, text=lines)

    def client(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*a, **kw)

    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", client)


CHUNKS = [{"message": {"thinking": "Let me think. "}}, {"message": {"thinking": "Paris."}},
          {"message": {"content": "Paris"}}]


async def test_think_flag_only_for_thinking_models(monkeypatch, temp_data_dir):
    from app.services.ollama_client import OllamaClient

    seen: list[dict] = []
    _mock_ollama(monkeypatch, ["completion", "thinking"], CHUNKS, seen)
    assert await OllamaClient().chat("qwen3.5:2b", [{"role": "user", "content": "hi"}]) == "Paris"
    assert seen[-1]["think"] is False  # internal calls never think

    seen.clear()
    _mock_ollama(monkeypatch, ["completion"], CHUNKS, seen)
    await OllamaClient().chat("llama3.2:1b", [{"role": "user", "content": "hi"}])
    assert "think" not in seen[-1]  # think=true would 400 on non-thinking models


async def test_thinking_deltas_are_marked(monkeypatch, temp_data_dir):
    from app.services.ollama_client import OllamaClient, ThinkingDelta

    seen: list[dict] = []
    _mock_ollama(monkeypatch, ["completion", "thinking"], CHUNKS, seen)
    pieces = [p async for p in OllamaClient().chat_stream("m", [], think=True, emit_thinking=True)]
    assert seen[-1]["think"] is True
    assert [isinstance(p, ThinkingDelta) for p in pieces] == [True, True, False]
    assert "".join(p for p in pieces if not isinstance(p, ThinkingDelta)) == "Paris"


@pytest.mark.parametrize(("mode", "role", "expected"), [
    ("auto", "reasoning", True), ("auto", "general", False), ("on", "small_fast", True), ("off", "reasoning", False),
])
def test_should_think(temp_data_dir, mode, role, expected):
    from app.core.config import settings
    from app.services.orchestrator import should_think

    settings.update({"thinking_mode": mode})
    assert should_think(role) is expected


def _stream(client, payload):
    events, t0 = [], time.monotonic()
    with client.stream("POST", "/api/chat", json=payload) as res:
        for line in res.iter_lines():
            if line.startswith("data:"):
                events.append((round(time.monotonic() - t0, 2), json.loads(line[5:])))
    return events


def test_thinking_streamed_not_persisted_and_done_is_fast(client, fake_ollama, monkeypatch):
    from app.core.config import settings
    from app.db import storage
    from app.services import memory_service
    from app.services.ollama_client import OllamaClient, ThinkingDelta

    settings.update({"memory_enabled": True, "recall_enabled": False, "folder_recall_enabled": False,
                     "notes_todos_context_enabled": False})

    async def stream(_self, model, messages, images_b64=None, options=None, format=None, think=None, emit_thinking=False):
        if emit_thinking:
            yield ThinkingDelta("weighing options… ")
        yield "Final answer."

    monkeypatch.setattr(OllamaClient, "chat_stream", stream)
    slow_called = asyncio.Event()

    async def slow_extract(text, conv):
        slow_called.set()
        await asyncio.sleep(3)
        return []

    monkeypatch.setattr(memory_service, "extract_from_text", slow_extract)
    conv = storage.create_conversation("t")["id"]
    events = _stream(client, {"conversation_id": conv, "message": "hello there friend"})
    kinds = [e["type"] for _, e in events]
    assert "thinking" in kinds and kinds[-1] == "done"
    assert events[-1][0] < 2.0  # done didn't wait for the 3s memory extraction
    replies = [m["content"] for m in storage.get_messages(conv) if m["role"] == "assistant"]
    assert replies == ["Final answer."]  # reasoning never saved as the reply
