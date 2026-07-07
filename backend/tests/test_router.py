"""Unit tests for the model router — covers regex-based fallback routing
across all capability buckets and verifies the reason string is always present."""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.ollama_client import OllamaError
from app.services.router import ModelRegistry, ModelRouter, RouteDecision


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

import asyncio


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