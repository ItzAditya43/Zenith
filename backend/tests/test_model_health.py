"""Pinned models Ollama refuses (retired / needs credits) stop trapping chats."""
from __future__ import annotations

import pytest

from app.services import model_health


@pytest.fixture(autouse=True)
def _clean():
    model_health.clear()
    yield
    model_health.clear()


def test_refusals_are_remembered_with_a_reason():
    model_health.note_error("minimax-m3:cloud", "Ollama returned 402 for model 'minimax-m3:cloud': {\"error\":\"Add usage credits\"}")
    model_health.note_error("old:cloud", "Ollama returned 410 for model 'old:cloud': retired")
    model_health.note_error("busy", "Ollama returned 500 for model 'busy': oops")
    model_health.note_error("slow", "Ollama did not produce a response within 60s")
    assert model_health.unavailable() == {
        "minimax-m3:cloud": {"status": 402, "reason": "needs Ollama credits or a subscription"},
        "old:cloud": {"status": 410, "reason": "retired by Ollama"},
    }


def test_entries_expire(monkeypatch):
    model_health.note_error("x:cloud", "Ollama returned 402 for model 'x:cloud': no")
    now = model_health.time.time()
    monkeypatch.setattr(model_health.time, "time", lambda: now + model_health.TTL_SECONDS + 1)
    assert not model_health.is_unavailable("x:cloud") and model_health.unavailable() == {}


def test_router_skips_a_dead_pin(temp_data_dir):
    from app.core.config import settings
    from app.services.router import ModelRouter

    settings.update({"model_overrides": {"general": "minimax-m3:cloud"}})
    router = ModelRouter()
    installed = ["qwen3.5:4b", "llama3.2:1b"]
    assert router._match_capability("general", installed) == "minimax-m3:cloud"
    model_health.note_error("minimax-m3:cloud", "Ollama returned 402 for model 'minimax-m3:cloud': pay")
    try:
        assert router._match_capability("general", installed) in installed
    finally:
        settings.update({"model_overrides": {"general": None}})


def test_repinning_clears_the_mark(client):
    model_health.note_error("minimax-m3:cloud", "Ollama returned 402 for model 'minimax-m3:cloud': pay")
    assert client.get("/api/models/unavailable").json() == {
        "minimax-m3:cloud": {"status": 402, "reason": "needs Ollama credits or a subscription"}}
    r = client.patch("/api/config", json={"model_overrides": {"general": "minimax-m3:cloud"}})
    assert r.status_code == 200
    assert client.get("/api/models/unavailable").json() == {}
    client.patch("/api/config", json={"model_overrides": {"general": None}})
