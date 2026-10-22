"""web_service.search backend routing: SearXNG with DuckDuckGo fallback."""
from __future__ import annotations


async def test_searxng_used_when_configured(temp_data_dir, monkeypatch):
    from app.core.config import settings
    from app.services import web_service

    settings.update({"web_search_backend": "searxng", "searxng_url": "http://sx.test"})

    async def sx(q, n):
        return [{"title": "S", "url": "https://s.test", "snippet": ""}]

    async def ddg(q, n):
        raise AssertionError("DuckDuckGo should not be hit")

    monkeypatch.setattr(web_service, "_search_searxng", sx)
    monkeypatch.setattr(web_service, "_search_duckduckgo", ddg)
    assert (await web_service.search("q"))[0]["title"] == "S"


async def test_searxng_failure_falls_back_to_duckduckgo(temp_data_dir, monkeypatch):
    from app.core.config import settings
    from app.services import web_service

    settings.update({"web_search_backend": "searxng", "searxng_url": "http://down.test"})

    async def sx(q, n):
        return []

    async def ddg(q, n):
        return [{"title": "D", "url": "https://d.test", "snippet": ""}]

    monkeypatch.setattr(web_service, "_search_searxng", sx)
    monkeypatch.setattr(web_service, "_search_duckduckgo", ddg)
    assert (await web_service.search("q"))[0]["title"] == "D"
    out = await web_service.test_search()
    assert out["backend"] == "duckduckgo (fallback)" and "returned nothing" in out["error"]


def test_searxng_env_implies_backend(temp_data_dir, monkeypatch):
    from app.core import config as cfg

    monkeypatch.setenv("ZENITH_SEARXNG_URL", "http://searxng:8080")
    cfg.settings.reload()
    assert cfg.settings.get("searxng_url") == "http://searxng:8080"
    assert cfg.settings.get("web_search_backend") == "searxng"
