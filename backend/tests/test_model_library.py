"""Ollama library browsing (parsed from saved ollama.com pages) and account/probe endpoints."""
from __future__ import annotations

from pathlib import Path

from app.services import model_library

DATA = Path(__file__).parent / "data"


def test_search_page_parses_models_capabilities_and_sizes():
    models = model_library.parse_search((DATA / "ollama_search.html").read_text())
    assert len(models) >= 15
    qwen = next(m for m in models if m["name"] == "qwen3.5")
    assert {"vision", "tools", "thinking"} <= set(qwen["capabilities"])
    assert "4b" in qwen["sizes"] and qwen["pulls"] > 1_000_000 and not qwen["cloud"]
    assert qwen["description"].startswith("Qwen 3.5")


def test_cloud_listing_marks_cloud_models():
    models = model_library.parse_search((DATA / "ollama_search_cloud.html").read_text())
    assert models and all(m["cloud"] for m in models)
    assert "'" in next(m["description"] for m in models if m["name"] == "glm-5.3")  # entities decoded


def test_model_page_lists_tags_with_sizes():
    tags = model_library.parse_model_page((DATA / "ollama_model_page.html").read_text(), "qwen3.5")
    by = {t["tag"]: t for t in tags}
    assert by["qwen3.5:4b"]["size"] == "3.3GB - 4.0GB" and by["qwen3.5:4b"]["size_gb"] == 4.0
    assert by["qwen3.5:4b"]["context"] == "256K"
    assert by["qwen3.5:122b"]["size_gb"] == 81.0


def test_garbage_pages_give_nothing():
    assert model_library.parse_search("<html>changed layout</html>") == []
    assert model_library.parse_model_page("<html></html>", "x") == []


def test_library_endpoint_reports_network_errors(client, monkeypatch):
    async def boom(*a, **k):
        raise model_library.LibraryError("Couldn't reach ollama.com.")
    monkeypatch.setattr(model_library, "search", boom)
    r = client.get("/api/models/library", params={"q": "qwen"})
    assert r.status_code == 502 and "ollama.com" in r.json()["detail"]


def test_bad_model_name_is_rejected():
    import asyncio

    try:
        asyncio.run(model_library.tags("../etc"))
    except model_library.LibraryError:
        return
    raise AssertionError("expected LibraryError")


def test_probe_marks_paid_models(fake_ollama):
    import asyncio

    from app.services import model_health

    model_health.clear()
    fake_ollama.queue(RuntimeError("placeholder"))  # replaced below
    fake_ollama.replies.clear()
    from app.services.ollama_client import OllamaError
    fake_ollama.queue(OllamaError("Ollama returned 402 for model 'm:cloud': {\"error\":\"Add usage credits\"}"))
    r = asyncio.run(model_health.probe("m:cloud"))
    assert r == {"model": "m:cloud", "ok": False, "reason": "needs Ollama credits or a subscription"}
    fake_ollama.queue("hi")
    assert asyncio.run(model_health.probe("m:cloud"))["ok"] is True
    assert not model_health.is_unavailable("m:cloud")
