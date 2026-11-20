"""API providers: OpenAI-compatible client, routing through OllamaClient, key storage, API."""
from __future__ import annotations

import json

import httpx
import pytest

from app.services import providers

CHAT_SSE = (
    'data: {"choices":[{"delta":{"reasoning_content":"thinking..."}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
    "data: [DONE]\n\n"
)


@pytest.fixture
def fake_api(monkeypatch, temp_data_dir):
    """An OpenAI-compatible server behind httpx.MockTransport. Records requests."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers.get("authorization") != "Bearer sk-test":
            return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})
        path = req.url.path
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-4.1"}, {"id": "text-embedding-3-small"}]})
        if path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        if path.endswith("/chat/completions"):
            body = json.loads(req.content)
            if body.get("tools"):
                return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [
                    {"function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}]}}]})
            if body["model"] == "missing":
                return httpx.Response(404, json={"error": {"message": "model not found"}})
            return httpx.Response(200, text=CHAT_SSE, headers={"content-type": "text/event-stream"})
        return httpx.Response(404)

    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(providers.httpx, "AsyncClient", Client)
    providers._models_cache.clear()
    providers.save({"id": "acme", "name": "Acme AI", "kind": "openai", "base_url": "https://api.acme.test/v1",
                    "api_key": "sk-test"})
    yield seen
    from app.core.config import settings
    settings.update({"providers": []})


def test_key_is_encrypted_and_never_public(fake_api):
    from app.core.config import settings

    stored = settings.get("providers")[0]["api_key"]
    assert stored.startswith("enc:v1:") and "sk-test" not in stored
    pub = providers.list_public()[0]
    assert pub["has_key"] is True and "api_key" not in pub and pub["local"] is False
    # Updating without a key keeps the old one.
    providers.save({"id": "acme", "kind": "openai", "base_url": "https://api.acme.test/v1", "name": "Acme 2"})
    assert providers._key(providers.get("acme")) == "sk-test"


def test_insecure_remote_url_and_bad_ids_are_refused(temp_data_dir):
    with pytest.raises(providers.ProviderError):
        providers.save({"id": "x", "kind": "openai", "base_url": "http://api.example.com/v1"})
    with pytest.raises(providers.ProviderError):
        providers.save({"id": "Bad Id!", "kind": "openai", "base_url": "https://a.test"})
    # Local servers may use plain http.
    assert providers.save({"id": "lm", "kind": "openai", "base_url": "http://localhost:1234/v1"})["local"] is True
    from app.core.config import settings
    settings.update({"providers": []})


async def test_chat_streams_through_the_shared_client(fake_api):
    from app.services.ollama_client import OllamaClient, ThinkingDelta

    pieces = [p async for p in OllamaClient().chat_stream("acme::gpt-4.1", [{"role": "user", "content": "hi"}],
                                                          images_b64=["iVBORw0KGgo="], emit_thinking=True)]
    assert "".join(p for p in pieces if not isinstance(p, ThinkingDelta)) == "Hello"
    assert any(isinstance(p, ThinkingDelta) for p in pieces)
    body = json.loads(fake_api[-1].content)
    assert body["model"] == "gpt-4.1" and body["stream"] is True
    img = body["messages"][-1]["content"][1]["image_url"]["url"]
    assert img.startswith("data:image/png;base64,")


async def test_json_format_tools_and_embeddings(fake_api):
    from app.services.ollama_client import OllamaClient

    c = OllamaClient()
    assert await c.chat("acme::gpt-4.1", [{"role": "user", "content": "x"}], format={"type": "object"}) == "Hello"
    body = json.loads(fake_api[-1].content)
    assert body["response_format"] == {"type": "json_object"} and "JSON Schema" in body["messages"][0]["content"]
    msg = await c.chat_tools("acme::gpt-4.1", [{"role": "user", "content": "x"}],
                             [{"type": "function", "function": {"name": "read_file", "parameters": {}}}])
    assert msg["tool_calls"][0]["function"]["name"] == "read_file"
    assert await c.embeddings("acme::text-embedding-3-small", "hello") == [0.1, 0.2]


async def test_errors_become_ollama_errors_and_mark_the_model(fake_api):
    from app.services import model_health
    from app.services.ollama_client import OllamaClient, OllamaError

    model_health.clear()
    with pytest.raises(OllamaError) as e:
        await OllamaClient().chat("acme::missing", [{"role": "user", "content": "x"}])
    assert "404" in str(e.value) and "model not found" in str(e.value)
    assert model_health.is_unavailable("acme::missing")
    providers.save({"id": "acme", "kind": "openai", "base_url": "https://api.acme.test/v1", "api_key": "wrong"})
    with pytest.raises(OllamaError) as e:
        await OllamaClient().chat("acme::gpt-4.1", [{"role": "user", "content": "x"}])
    assert "API key was rejected" in str(e.value)
    model_health.clear()


async def test_models_are_listed_alongside_ollama_and_count_as_remote(fake_api, monkeypatch):
    from app.services.ollama_client import OllamaClient, OllamaError
    from app.services.router import is_cloud_model

    async def ollama_down(self):
        raise OllamaError("Can't reach Ollama")
    monkeypatch.setattr(OllamaClient, "_ollama_models", ollama_down)
    names = [m["name"] for m in await OllamaClient().list_models()]
    assert names == ["acme::gpt-4.1", "acme::text-embedding-3-small"]
    assert is_cloud_model("acme::gpt-4.1") is True
    providers.save({"id": "lm", "kind": "openai", "base_url": "http://127.0.0.1:1234/v1"})
    assert is_cloud_model("lm::qwen") is False
    assert "vision" in await OllamaClient().capabilities("acme::gpt-4.1")


def test_providers_api(client, fake_api):
    r = client.get("/api/providers")
    assert r.status_code == 200 and r.json()["providers"][0]["id"] == "acme"
    assert "sk-test" not in r.text
    assert "providers" not in client.get("/api/config").json()
    t = client.post("/api/providers/acme/test").json()
    assert t["ok"] and t["count"] == 2
    assert any(p["id"] == "anthropic" for p in client.get("/api/providers/presets").json()["presets"])
    assert client.post("/api/providers", json={"id": "x", "base_url": "http://evil.example/v1"}).status_code == 400
    assert client.delete("/api/providers/acme").json() == {"deleted": "acme"}
    assert client.delete("/api/providers/acme").status_code == 404


def test_anthropic_message_shaping():
    system, turns = providers._anthropic_messages(
        [{"role": "system", "content": "Be brief."}, {"role": "assistant", "content": "earlier"},
         {"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
        ["/9j/4AAQSkZJRg=="], "json")
    assert system.startswith("Be brief.") and "JSON" in system
    assert turns[0] == {"role": "user", "content": "(continue)"}
    last = turns[-1]["content"]
    assert last[0]["source"]["media_type"] == "image/jpeg" and last[-1]["text"] == "a\n\nb"
    kw = providers._anthropic_call_kwargs("claude-opus-5-5", system, turns, 1000, True)
    assert kw["fallbacks"] == "default" and kw["thinking"]["display"] == "summarized"
    assert "fallbacks" not in providers._anthropic_call_kwargs("claude-haiku-4-5", "", turns, 1000, False)
