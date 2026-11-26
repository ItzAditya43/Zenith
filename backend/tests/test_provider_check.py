"""Guided provider check: each step, the first failure, and a fix hint.
The provider's HTTP calls are replaced with fakes."""
from __future__ import annotations

import pytest

from app.services import providers


@pytest.fixture
def fake_api(monkeypatch):
    state = {"models": ["gpt-4o-mini", "text-embedding-3-small", "gpt-4o"], "fail": None, "reply": "OK"}

    async def models(p):
        if state["fail"]:
            raise providers.ProviderError(state["fail"])
        return state["models"]

    async def stream(p, model, msgs, images, options=None, fmt=None, emit_thinking=False, timeout=600):
        state["chat_model"] = model
        for w in state["reply"].split():
            yield w

    async def tools(p, model, msgs, tools, timeout=600):
        return {"content": "", "tool_calls": [{"function": {"name": "get_time", "arguments": "{}"}}]}

    async def embed(p, model, text):
        return [0.1] * 8

    monkeypatch.setattr(providers, "_openai_models", models)
    monkeypatch.setattr(providers, "openai_stream", stream)
    monkeypatch.setattr(providers, "openai_tools", tools)
    monkeypatch.setattr(providers, "openai_embed", embed)
    return state


def _steps(r):
    return {s["id"]: s for s in r["steps"]}


def test_happy_path_thorough(client, fake_api):
    r = client.post("/api/providers/check", json={"base_url": "https://api.openai.com/v1", "api_key": "sk-test", "thorough": True}).json()
    s = _steps(r)
    assert r["ok"] and [x["id"] for x in r["steps"]] == ["address", "reach", "key", "models", "chat", "tools", "embeddings"]
    assert fake_api["chat_model"] == "gpt-4o-mini"  # cheap model for the check
    assert "8 dimensions" in s["embeddings"]["detail"] and "called the tool" in s["tools"]["detail"]
    caps = {m["name"]: m["caps"] for m in r["models"]}
    assert "vision" in caps["gpt-4o"] and caps["text-embedding-3-small"] == ["embedding"]
    assert "may cost money" in r["next"]
    assert "sk-test" not in str(r)


@pytest.mark.parametrize("error,fix", [
    ("OpenAI returned 401 (the API key was rejected): bad", "fresh key from https://platform.openai.com/api-keys"),
    ("OpenAI returned 402 (the account needs credits): x", "no credit"),
    ("OpenAI returned 429 (rate limited or out of quota): x", "rate limit"),
])
def test_key_failures_explain_the_fix(client, fake_api, error, fix):
    fake_api["fail"] = error
    r = client.post("/api/providers/check", json={"base_url": "https://api.openai.com/v1", "api_key": "sk-x"}).json()
    s = _steps(r)
    assert not r["ok"] and s["reach"]["ok"] and s["key"]["ok"] is False and fix in s["key"]["fix"]


def test_unreachable_local_server_and_bad_addresses(client, fake_api):
    fake_api["fail"] = "Can't reach LM Studio at http://localhost:1234/v1."
    r = client.post("/api/providers/check", json={"base_url": "http://localhost:1234/v1"}).json()
    assert _steps(r)["reach"]["ok"] is False and "Start server" in _steps(r)["reach"]["fix"]
    r = client.post("/api/providers/check", json={"base_url": "http://api.example.com/v1", "api_key": "k"}).json()
    assert _steps(r)["address"]["ok"] is False and "https" in _steps(r)["address"]["fix"]
    r = client.post("/api/providers/check", json={"base_url": "https://api.example.com/v1"}).json()
    assert _steps(r)["key"]["ok"] is False


def test_local_without_models_and_saved_provider(client, fake_api):
    fake_api["models"] = []
    r = client.post("/api/providers/check", json={"base_url": "http://localhost:1234/v1"}).json()
    assert _steps(r)["key"]["detail"] == "Not needed for this server" and _steps(r)["models"]["ok"] is False
    fake_api["models"] = ["llama-3.1-8b"]
    client.post("/api/providers", json={"id": "lms", "name": "LM Studio", "base_url": "http://localhost:1234/v1"})
    r = client.post("/api/providers/check", json={"id": "lms"}).json()
    assert r["ok"] and r["chat_model"] == "llama-3.1-8b" and "may cost money" not in r["next"]
