"""Unit tests for the model router — covers regex-based fallback routing
across all capability buckets and verifies the reason string is always present."""
from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.services.ollama_client import OllamaError
from app.services.router import ModelRegistry, ModelRouter


class _FakeClient:
    """Minimal stand-in for OllamaClient that returns a fixed model list."""

    def __init__(self, models: list[str], fail: bool = False):
        self._models = models
        self._fail = fail

    async def list_models(self):
        if self._fail:
            raise OllamaError("simulated ollama down")
        return [{"name": m} for m in self._models]


def _make_router(models: list[str]) -> ModelRouter:
    registry = ModelRegistry(client=_FakeClient(models), ttl=60.0)  # type: ignore[arg-type]
    return ModelRouter(registry=registry)


def _installed() -> list[str]:
    """A representative set covering every capability bucket."""
    return [
        "llama3.2:latest",       # general
        "qwen2.5-coder:7b",      # code
        "deepseek-r1:8b",        # reasoning
        "llava:13b",             # vision
        "phi3:mini",             # small_fast
    ]


def test_vision_attachment_routes_to_vision_model():
    router = _make_router(_installed())
    decision = await_or_sync(
        router.decide(text="What's in this image?", has_image=True)
    )
    assert decision.model == "llava:13b"
    assert decision.role == "vision"
    assert "vision" in decision.reason.lower() or "image" in decision.reason.lower()


def test_code_message_routes_to_code_model():
    router = _make_router(_installed())
    decision = await_or_sync(
        router.decide(text="Write a sorting algorithm in Python")
    )
    assert decision.model == "qwen2.5-coder:7b"
    assert decision.role == "code"
    assert decision.reason  # always non-empty


def test_reasoning_message_routes_to_reasoning_model():
    router = _make_router(_installed())
    decision = await_or_sync(
        router.decide(text="Solve this step by step: prove sqrt(2) is irrational")
    )
    assert decision.model == "deepseek-r1:8b"
    assert decision.role == "reasoning"


def test_short_greeting_routes_to_small_fast():
    router = _make_router(_installed())
    decision = await_or_sync(router.decide(text="hi"))
    assert decision.model == "phi3:mini"
    assert decision.role == "small_fast"


def test_general_message_routes_to_general_model():
    router = _make_router(_installed())
    decision = await_or_sync(
        router.decide(text="Tell me about the history of the Roman Empire.")
    )
    assert decision.model == "llama3.2:latest"
    assert decision.role == "general"


def test_no_models_raises_ollama_error():
    router = _make_router([])
    with pytest.raises(OllamaError):
        await_or_sync(router.decide(text="hello"))


def test_missing_capability_falls_back_to_general():
    # No code model installed — should fall back to general gracefully.
    router = _make_router(["llama3.2:latest", "llava:13b"])
    decision = await_or_sync(
        router.decide(text="Write a sorting algorithm")
    )
    assert decision.model == "llama3.2:latest"
    assert "fall back" in decision.reason.lower() or "fallback" in decision.reason.lower()


def test_model_override_takes_precedence():
    # Save & restore the override to avoid leaking state between tests.
    overrides = settings.get("model_overrides", {}) or {}
    try:
        settings.set("model_overrides", {**overrides, "code": "llama3.2:latest"})
        router = _make_router(_installed())
        decision = await_or_sync(
            router.decide(text="Write a sorting algorithm")
        )
        assert decision.model == "llama3.2:latest"
        assert decision.role == "code"
    finally:
        settings.set("model_overrides", overrides)


def test_video_attachment_also_routes_to_vision():
    router = _make_router(_installed())
    decision = await_or_sync(router.decide(text="What happens here?", has_video=True))
    assert decision.role == "vision"
    assert decision.model == "llava:13b"


def test_no_vision_model_with_image_falls_back_to_general():
    router = _make_router(["llama3.2:latest", "qwen2.5-coder:7b"])
    decision = await_or_sync(router.decide(text="describe this", has_image=True))
    # Falls through to general because no vision model is installed.
    assert decision.role == "general"
    assert decision.model == "llama3.2:latest"


# --- helpers ---------------------------------------------------------------



def await_or_sync(coro):
    """Run an awaitable from sync test code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # In an async context, return the coroutine for the caller to await.
            return coro
    except RuntimeError:
        pass
    return asyncio.run(coro)

@pytest.mark.parametrize("text", [
    "Why does my Rust borrow checker complain about this struct lifetime?",
    "Write a bash script that renames every .jpeg file to .jpg",
    "SELECT * FROM users WHERE id = 1 -- why is this query slow?",
    "my golang service leaks goroutines",
])
def test_language_and_sql_prompts_hint_code(text):
    from app.services.router import _CODE_HINTS

    assert _CODE_HINTS.search(text)


@pytest.mark.parametrize("text", [
    "What are some good houseplants for a dark apartment?",
    "Summarise the plot of Pride and Prejudice",
    "Select a nice restaurant from this list for Friday",
])
def test_plain_prompts_do_not_hint_code(text):
    from app.services.router import _CODE_HINTS

    assert not _CODE_HINTS.search(text)


# --- cloud models never auto-routed; small-model detection; semantic margin ---


def test_cloud_model_detection():
    from app.services.router import is_cloud_model

    for name in ("gpt-oss:120b-cloud", "glm-5.3:cloud", "mistral-large-3:675b-cloud"):
        assert is_cloud_model(name)
    for name in ("llama3.2:1b", "qwen2.5-coder:3b", "cloudy-model:7b", "nomic-embed-text"):
        assert not is_cloud_model(name)


def _router(models):
    return ModelRouter(registry=ModelRegistry(client=_FakeClient(models), ttl=0))


@pytest.mark.asyncio
async def test_general_chat_never_routes_to_a_cloud_model():
    settings.update({"model_overrides": {r: None for r in ("vision", "code", "reasoning", "embedding", "small_fast", "general")},
                     "route_to_cloud_models": False})
    r = _router(["mistral-large-3:675b-cloud", "llama3:latest"])
    d = await r.decide(text="What are good houseplants for a dark flat?")
    assert d.model == "llama3:latest"
    assert await r.registry.models() == ["llama3:latest"]
    assert await r.registry.all_models() == ["mistral-large-3:675b-cloud", "llama3:latest"]


@pytest.mark.asyncio
async def test_only_cloud_models_installed_gives_a_clear_error():
    settings.update({"route_to_cloud_models": False, "model_overrides": {"general": None}})
    with pytest.raises(OllamaError, match="No local models installed"):
        await _router(["gpt-oss:120b-cloud"]).decide(text="hello there friend")


@pytest.mark.asyncio
async def test_cloud_routing_is_opt_in_and_pins_are_honoured():
    settings.update({"route_to_cloud_models": True})
    assert await _router(["gpt-oss:120b-cloud"]).registry.models() == ["gpt-oss:120b-cloud"]
    settings.update({"route_to_cloud_models": False, "model_overrides": {"general": "glm-5.3:cloud"}})
    d = await _router(["glm-5.3:cloud", "llama3:latest"]).decide(text="What are good houseplants for a dark flat?")
    assert d.model == "glm-5.3:cloud"
    settings.update({"model_overrides": {"general": None}})


@pytest.mark.asyncio
async def test_small_models_detected_by_size():
    settings.update({"route_to_cloud_models": False, "model_overrides": {r: None for r in ("small_fast", "general")}})
    r = _router(["llama3:latest", "cyberuser42/DeepSeek-R1-Distill-Qwen-1.5B:latest", "llama3.2:1b", "nomic-embed-text"])
    d = await r.decide(text="hi")
    assert d.role == "small_fast" and d.model == "llama3.2:1b"


def test_best_fit_prefers_largest_model_that_fits(monkeypatch):
    from app.services import router as router_mod

    monkeypatch.setattr(router_mod, "_memory_budget_gb", lambda: 8.0)
    assert router_mod._best_fit(["llama3.2:1b", "qwen3.5:4b", "llama3:70b"]) == "qwen3.5:4b"
    monkeypatch.setattr(router_mod, "_memory_budget_gb", lambda: 64.0)
    assert router_mod._best_fit(["llama3.2:1b", "qwen3.5:4b", "llama3:70b"]) == "llama3:70b"
    monkeypatch.setattr(router_mod, "_memory_budget_gb", lambda: None)
    assert router_mod._best_fit(["llama3.2:1b", "qwen3.5:4b"]) == "qwen3.5:4b"


@pytest.mark.asyncio
async def test_reported_parameter_size_used_for_untagged_models(monkeypatch):
    from app.services import router as router_mod

    class Client:
        async def list_models(self):
            return [{"name": "llama3:latest", "details": {"parameter_size": "8.0B"}},
                    {"name": "llama3.2:1b", "details": {"parameter_size": "1.2B"}}]

    monkeypatch.setattr(router_mod, "_memory_budget_gb", lambda: 16.0)
    reg = ModelRegistry(client=Client(), ttl=0)
    await reg.models()
    assert router_mod._params_b("llama3:latest") == 8.0
    assert router_mod._best_fit(["llama3.2:1b", "llama3:latest"]) == "llama3:latest"
    assert router_mod._parse_reported("494.03M") == pytest.approx(0.494, rel=1e-3)


def test_general_pool_excludes_specialised_models(monkeypatch):
    from app.services import router as router_mod

    monkeypatch.setattr(router_mod, "_memory_budget_gb", lambda: 16.0)
    settings.update({"model_overrides": {r: None for r in ("vision", "code", "reasoning", "embedding", "small_fast", "general")}})
    r = ModelRouter(registry=ModelRegistry(client=_FakeClient([]), ttl=0))
    installed = ["qwen2.5vl:7b", "qwen2.5-coder:7b", "qwen3.5:4b"]
    assert r._match_capability("general", installed) == "qwen3.5:4b"
    assert r._match_capability("code", installed) == "qwen2.5-coder:7b"
    assert r._match_capability("general", ["qwen2.5-coder:7b"]) == "qwen2.5-coder:7b"  # nothing else left


@pytest.mark.asyncio
async def test_capability_routing_finds_unnamed_vision_model(monkeypatch):
    from app.services import router as router_mod

    class Client:
        async def list_models(self):
            return [{"name": "qwen3.5:2b"}, {"name": "llama3.2:1b"}]

        async def capabilities(self, name):
            return frozenset({"completion", "vision"} if name.startswith("qwen3.5") else {"completion"})

    router_mod._model_caps.clear()
    settings.update({"model_overrides": {r: None for r in ("vision", "general", "small_fast")}, "route_to_cloud_models": False})
    r = ModelRouter(registry=ModelRegistry(client=Client(), ttl=0))
    d = await r.decide(text="what is in this picture?", has_image=True)
    assert d.model == "qwen3.5:2b" and d.role == "vision"


def test_sticky_breaks_when_topic_clearly_moves(monkeypatch):
    import asyncio

    from app.services import router as router_mod

    async def fake_rank(self, text, embed_model):
        return [("general", 0.9), ("code", 0.3)]

    monkeypatch.setattr("app.services.embedding_router.EmbeddingRouter.rank", fake_rank)
    settings.update({"model_overrides": {r: None for r in ("code", "general", "embedding")}, "route_to_cloud_models": False})
    r = ModelRouter(registry=ModelRegistry(client=_FakeClient(["qwen2.5-coder:7b", "llama3:8b", "nomic-embed-text"]), ttl=0))
    d = asyncio.run(r.decide(text="Who owns the budget in this plan?", history_last_model="qwen2.5-coder:7b"))
    assert d.role != "sticky" and d.model == "llama3:8b"
    router_mod._model_caps.clear()
