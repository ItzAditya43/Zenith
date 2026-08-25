"""Unit tests for the router's learning-from-overrides feedback loop:
`storage.dominant_override_model` and its use in `ModelRouter` to nudge
weak/ambiguous routing decisions toward a model the user has repeatedly
and consistently redirected to."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from app.services.ollama_client import OllamaError
from app.services.router import ModelRegistry, ModelRouter


def await_or_sync(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return coro
    except RuntimeError:
        pass
    return asyncio.run(coro)


class _FakeClient:
    def __init__(self, models: list[str]):
        self._models = models

    async def list_models(self):
        return [{"name": m} for m in self._models]


def _make_router(models: list[str]) -> ModelRouter:
    registry = ModelRegistry(client=_FakeClient(models), ttl=60.0)  # type: ignore[arg-type]
    return ModelRouter(registry=registry)


@pytest.fixture
def temp_data_dir(monkeypatch):
    d = tempfile.mkdtemp(prefix="cortex-test-")
    monkeypatch.setenv("CORTEX_DATA_DIR", d)
    from app.core import config as cfg
    from app.db import storage

    cfg.refresh_paths()
    cfg.settings.reload()
    storage.init_db()
    yield Path(d)
    cfg.refresh_paths()
    cfg.settings.reload()


def test_dominant_override_model_needs_min_count_and_majority(temp_data_dir):
    from app.db import storage

    # Only two overrides for "code" -> below min_count=3, should be None.
    storage.log_routing_override("msg1", "code", "qwen2.5-coder:7b", "deepseek-r1:8b")
    storage.log_routing_override("msg2", "code", "qwen2.5-coder:7b", "deepseek-r1:8b")
    assert storage.dominant_override_model("code") is None

    # A third repeat of the same override pushes it over min_count and it's
    # a clean 100% majority -> should now return the consistently-chosen model.
    storage.log_routing_override("msg3", "code", "qwen2.5-coder:7b", "deepseek-r1:8b")
    assert storage.dominant_override_model("code") == "deepseek-r1:8b"

    # A role where the top model's raw count never reaches min_count should
    # stay None even though it's a majority of a small sample.
    storage.log_routing_override("msg4", "reasoning", "deepseek-r1:8b", "llama3.2:latest")
    storage.log_routing_override("msg5", "reasoning", "deepseek-r1:8b", "phi3:mini")
    storage.log_routing_override("msg6", "reasoning", "deepseek-r1:8b", "llama3.2:latest")
    # llama3.2 has 2/3 (66% majority) but count=2 < min_count=3 -> still None.
    assert storage.dominant_override_model("reasoning") is None

    # One more repeat pushes llama3.2's count to 3 with a 3/4 (75%) majority.
    storage.log_routing_override("msg7", "reasoning", "deepseek-r1:8b", "llama3.2:latest")
    assert storage.dominant_override_model("reasoning") == "llama3.2:latest"


def test_dominant_override_model_empty_table_returns_none(temp_data_dir):
    from app.db import storage

    assert storage.dominant_override_model("code") is None
    assert storage.dominant_override_model("general") is None


def test_router_unaffected_without_override_history(temp_data_dir):
    """Fresh install / empty overrides table -> today's exact behavior."""
    router = _make_router([
        "llama3.2:latest", "qwen2.5-coder:7b", "deepseek-r1:8b", "llava:13b", "phi3:mini",
    ])
    decision = await_or_sync(router.decide(text="Write a sorting algorithm in Python"))
    assert decision.model == "qwen2.5-coder:7b"
    assert decision.role == "code"


def test_router_shifts_model_with_strong_override_pattern(temp_data_dir):
    """Once a clear, repeated override pattern exists for a role, the
    router should learn it and route future weak/ambiguous 'code' picks
    to the model the user consistently chose instead."""
    from app.db import storage

    installed = [
        "llama3.2:latest", "qwen2.5-coder:7b", "deepseek-r1:8b", "llava:13b", "phi3:mini",
    ]

    # Baseline: without history, code routes to the keyword-matched model.
    router = _make_router(installed)
    baseline = await_or_sync(router.decide(text="Write a sorting algorithm in Python"))
    assert baseline.model == "qwen2.5-coder:7b"

    # Seed a strong, repeated override pattern: every time the router
    # auto-picked qwen2.5-coder:7b for "code", the user actually sent it to
    # deepseek-r1:8b instead.
    for i in range(4):
        storage.log_routing_override(
            f"code msg {i}", "code", "qwen2.5-coder:7b", "deepseek-r1:8b"
        )
    assert storage.dominant_override_model("code") == "deepseek-r1:8b"

    router2 = _make_router(installed)
    learned = await_or_sync(router2.decide(text="Write a sorting algorithm in Python"))
    assert learned.model == "deepseek-r1:8b"
    assert learned.role == "code"


def test_router_ignores_weak_override_pattern(temp_data_dir):
    """A single override shouldn't be enough to change routing."""
    from app.db import storage

    installed = [
        "llama3.2:latest", "qwen2.5-coder:7b", "deepseek-r1:8b", "llava:13b", "phi3:mini",
    ]
    storage.log_routing_override("only once", "code", "qwen2.5-coder:7b", "deepseek-r1:8b")
    assert storage.dominant_override_model("code") is None

    router = _make_router(installed)
    decision = await_or_sync(router.decide(text="Write a sorting algorithm in Python"))
    assert decision.model == "qwen2.5-coder:7b"
