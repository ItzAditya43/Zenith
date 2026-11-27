"""A model pull stops with a clear message when it won't fit on disk."""
from __future__ import annotations

import asyncio
from collections import namedtuple

import pytest

from app.api import system
from app.services.ollama_client import OllamaError


class FakeClient:
    async def pull_model(self, name):
        yield {"status": "pulling manifest"}
        yield {"status": "pulling abc", "digest": "sha256:abc", "total": 5_000_000_000, "completed": 0}
        yield {"status": "success"}


async def _drain(gen):
    return [e async for e in gen]


def test_pull_stops_when_disk_is_full(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "_ollama_models_dir", lambda: str(tmp_path))
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("shutil.disk_usage", lambda p: Usage(10**12, 0, 2_000_000_000))
    with pytest.raises(OllamaError, match="Not enough disk space"):
        asyncio.run(_drain(system._pull_with_space_check(FakeClient(), "big:7b")))


def test_pull_passes_when_space_is_fine(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "_ollama_models_dir", lambda: str(tmp_path))
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("shutil.disk_usage", lambda p: Usage(10**12, 0, 50_000_000_000))
    evs = asyncio.run(_drain(system._pull_with_space_check(FakeClient(), "big:7b")))
    assert evs[-1]["status"] == "success"
