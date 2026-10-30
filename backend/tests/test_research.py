"""Deep Research loop (research_service) against the scripted fake Ollama,
with web_service stubbed — plus the private-address guard on
model-initiated fetches (web_service.fetch_url(allow_private=False))."""
from __future__ import annotations

import httpx
import pytest

from tests.conftest import collect


@pytest.fixture
def research(fake_ollama, monkeypatch):
    from app.core.config import settings
    from app.db import storage
    from app.services import web_service

    settings.update({"research_max_iterations": 6, "memory_enabled": False, "recall_enabled": False,
                     "folder_recall_enabled": False, "notes_todos_context_enabled": False})
    fetched: list[str] = []

    async def search(query, max_results=None):
        return [{"url": "https://example.com/solar", "title": "Solar 2026", "snippet": "solar is cheap"}]

    async def fetch(url, allow_private=True):
        fetched.append((url, allow_private))
        if "dead" in url:
            return None
        return {"url": url, "title": "Solar 2026", "text": "Solar module prices fell 20% in 2026."}

    monkeypatch.setattr(web_service, "search", search)
    monkeypatch.setattr(web_service, "fetch_url", fetch)
    conv = storage.create_conversation("research")["id"]
    return {"conv": conv, "fake": fake_ollama, "fetched": fetched}


async def _run(conv, topic="state of solar power in 2026"):
    from app.services import research_service

    return await collect(research_service.run_deep_research(conv, topic, []))


async def test_search_fetch_then_cited_report(research):
    research["fake"].tool("web_search", query="solar prices 2026")
    research["fake"].tool("fetch_url", url="https://example.com/solar")
    research["fake"].final("## Prices\nModules fell 20% [Solar 2026](https://example.com/solar).")
    events = await _run(research["conv"])
    types = [e["type"] for e in events]
    assert types.count("tool_result") == 2
    assert next(e for e in events if e["type"] == "sources")["sources"] == [
        {"url": "https://example.com/solar", "title": "Solar 2026"}
    ]
    assert events[-1]["full_text"].startswith("## Prices")
    # model-chosen URLs are fetched with the private-address guard on
    assert research["fetched"] == [("https://example.com/solar", False)]


async def test_ungrounded_report_is_refused_until_it_searches(research):
    research["fake"].final("Made-up report with fake citations")
    research["fake"].tool("web_search", query="solar")
    research["fake"].final("Grounded report")
    events = await _run(research["conv"])
    assert "requires actually looking things up" in research["fake"].prompts()[1]
    assert events[-1]["full_text"] == "Grounded report"


async def test_disallowed_tools_are_never_run(research, tmp_path):
    target = tmp_path / "should_not_exist"
    research["fake"].tool("bash", command=f"touch {target}")
    research["fake"].tool("write_file", path=str(target), content="x")
    research["fake"].tool("web_search", query="solar")
    research["fake"].final("ok")
    events = await _run(research["conv"])
    assert not target.exists()
    assert [e["tool"] for e in events if e["type"] == "tool_call"] == ["web_search"]
    assert "disallowed tool 'bash'" in research["fake"].prompts()[1]


async def test_failed_fetch_is_not_cited(research):
    research["fake"].tool("fetch_url", url="https://dead.example.com/x").final("thin report")
    events = await _run(research["conv"])
    assert not any(e["type"] == "sources" for e in events)


async def test_malformed_json_before_any_tool_is_retried(research):
    research["fake"].queue("Sure! Solar is great.")  # prose, no JSON, no tool used
    research["fake"].tool("web_search", query="solar").final("real report")
    events = await _run(research["conv"])
    assert "wasn't valid JSON" in research["fake"].prompts()[1]
    assert events[-1]["full_text"] == "real report"


async def test_malformed_final_after_tool_is_cleaned(research):
    research["fake"].tool("web_search", query="solar")
    research["fake"].queue('{"final": "## Report\nIt has "unescaped" quotes"}')
    events = await _run(research["conv"])
    assert events[-1]["full_text"].startswith("## Report")
    assert '{"final"' not in events[-1]["full_text"]


async def test_step_limit_still_produces_a_report_from_gathered_material(research):
    from app.core.config import settings

    settings.update({"research_max_iterations": 2})
    research["fake"].tool("web_search", query="a").tool("fetch_url", url="https://example.com/solar")
    research["fake"].final("## Partial\nPrices fell 20%.")
    events = await _run(research["conv"])
    text = events[-1]["full_text"]
    assert "step limit" in text and "## Partial" in text
    assert "no more tools" in research["fake"].prompts()[-1]


async def test_model_that_never_searches_gets_honest_message(research):
    from app.core.config import settings

    settings.update({"research_max_iterations": 2})
    research["fake"].final("guess").final("guess again")
    events = await _run(research["conv"])
    assert "wasn't able to get this model to actually search" in events[-1]["full_text"]


async def test_ollama_error_ends_with_error_event(research):
    from app.services.ollama_client import OllamaError

    research["fake"].queue(OllamaError("down"))
    events = await _run(research["conv"])
    assert events[-1] == {"type": "error", "message": "down"}


# --- private-address guard ------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1", "172.16.4.4", "169.254.169.254",
     "[::1]", "::ffff:127.0.0.1", "0.0.0.0", "printer.local", "db.internal", "no-such-host.invalid"],
)
def test_non_public_hosts_are_detected(host):
    from app.services.web_service import host_is_non_public

    assert host_is_non_public(host)


def test_public_ip_is_allowed():
    from app.services.web_service import host_is_non_public

    assert not host_is_non_public("93.184.215.14")


async def test_guard_blocks_private_and_redirects_but_not_user_urls(monkeypatch, temp_data_dir):
    """Exercise the real httpx hook: a public URL that redirects to the
    loopback API is blocked for model fetches; user-pasted URLs aren't."""
    from app.services import web_service

    monkeypatch.setattr(web_service, "host_is_non_public", lambda h: h in ("127.0.0.1", "internal.test"))
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "public.test":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8420/api/config"})
        return httpx.Response(200, text="secret config", headers={"content-type": "text/plain"})

    real_client = httpx.AsyncClient

    def client_with_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(web_service.httpx, "AsyncClient", client_with_transport)

    assert await web_service.fetch_url("http://public.test/page", allow_private=False) is None
    assert seen == ["http://public.test/page"]  # redirect target never requested
    assert await web_service.fetch_url("http://internal.test/", allow_private=False) is None

    seen.clear()
    page = await web_service.fetch_url("http://public.test/page", allow_private=True)
    assert page and page["text"] == "secret config"
    assert seen[-1] == "http://127.0.0.1:8420/api/config"


async def test_agent_fetch_url_uses_the_guard(monkeypatch):
    from app.services import agent_service, web_service

    calls = []

    async def fetch(url, allow_private=True):
        calls.append(allow_private)
        return None

    monkeypatch.setattr(web_service, "fetch_url", fetch)
    out = await agent_service._run_fetch_url({"url": "http://127.0.0.1:8420/api/config"}, 1000)
    assert calls == [False] and "blocked" in out
