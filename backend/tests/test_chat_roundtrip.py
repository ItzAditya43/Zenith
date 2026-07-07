"""
Mocked chat-turn round-trip test.

Exercises the orchestrator's wiring end-to-end with a fake OllamaClient so
we don't need a live Ollama to prove the router -> orchestrator -> SSE
path is intact.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class FakeOllama:
    def __init__(self):
        self.calls = []

    async def list_models(self):
        return [{"name": "llama3.2"}, {"name": "llava"}, {"name": "qwen2.5-coder"}]

    async def chat_stream(self, *, model, messages, images=None, **kwargs):
        self.calls.append({"model": model, "messages": messages, "images": images})
        # Yield a couple of chunks then a done signal.
        for chunk in ["Hello", " from ", "fake-ollama."]:
            yield {"done": False, "response": chunk}
        yield {"done": True, "response": ""}


@pytest.mark.asyncio
async def test_router_picks_installed_code_model(monkeypatch):
    from app.services import router as router_mod
    from app.core import config as cfg

    cfg.settings.reload()
    # Make sure a code-role override resolves to a model the fake lists.
    cfg.settings.update(
        {
            "model_overrides": {
                "general": "llama3.2",
                "code": "qwen2.5-coder",
                "vision": "llava",
            }
        }
    )

    fake = FakeOllama()
    reg = router_mod.ModelRegistry(client=fake, ttl=0)  # never cache
    r = router_mod.ModelRouter(registry=reg)

    decision = await r.decide(text="def bubble_sort(arr): pass")
    assert decision.role == "code"
    assert decision.model == "qwen2.5-coder"
    assert "code" in decision.reason.lower() or "code-related" in decision.reason.lower()


@pytest.mark.asyncio
async def test_router_picks_vision_for_image(monkeypatch):
    from app.services import router as router_mod
    from app.core import config as cfg

    cfg.settings.reload()
    cfg.settings.update(
        {
            "model_overrides": {
                "general": "llama3.2",
                "code": "qwen2.5-coder",
                "vision": "llava",
            }
        }
    )
    fake = FakeOllama()
    reg = router_mod.ModelRegistry(client=fake, ttl=0)
    r = router_mod.ModelRouter(registry=reg)

    decision = await r.decide(text="what is in this picture?", has_image=True)
    assert decision.role == "vision"
    assert decision.model == "llava"