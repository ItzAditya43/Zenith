"""Routing policy (local only / manual remote / allow selected), provider
role eligibility, usage accounting and monthly spend limits."""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import providers


@pytest.fixture
def provs(fake_ollama):
    settings.update({"providers": [], "routing_policy": "", "routing_allowed_providers": [], "route_to_cloud_models": False})
    providers.save({"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "api_key": "sk-x",
                    "price_in": 2.5, "price_out": 10, "monthly_limit": 0.01, "roles": ["code"]})
    providers.save({"id": "lms", "name": "LM Studio", "base_url": "http://localhost:1234/v1"})
    yield
    settings.update({"providers": [], "routing_policy": "", "routing_allowed_providers": []})


def test_policy_decides_automatic_and_manual_use(provs):
    from app.services.router import auto_allowed, manual_allowed, routing_policy

    assert routing_policy() == "manual_remote"
    assert auto_allowed("llama3.2:3b") and auto_allowed("lms::qwen")  # local server counts as local
    assert not auto_allowed("openai::gpt-4o") and not auto_allowed("glm-5.3:cloud")
    assert manual_allowed("openai::gpt-4o")

    settings.update({"routing_policy": "allow_selected", "routing_allowed_providers": ["openai"]})
    assert auto_allowed("openai::gpt-4o", "code") and not auto_allowed("openai::gpt-4o", "general")  # role eligibility
    assert not auto_allowed("glm-5.3:cloud")
    settings.update({"routing_allowed_providers": ["ollama-cloud"]})
    assert auto_allowed("glm-5.3:cloud") and not auto_allowed("openai::gpt-4o")

    settings.update({"routing_policy": "local_only"})
    assert not manual_allowed("openai::gpt-4o") and not manual_allowed("glm-5.3:cloud") and manual_allowed("lms::x")

    settings.update({"routing_policy": "", "route_to_cloud_models": True})  # the old switch still means "allow all"
    assert routing_policy() == "allow_selected" and auto_allowed("glm-5.3:cloud")


async def test_usage_recorded_and_limit_blocks(provs, monkeypatch):
    from app.services import spend_service

    async def fake_stream(p, model, msgs, images=None, options=None, fmt=None, emit_thinking=False, timeout=600, usage=None):
        usage.update(input=1000, output=500)
        yield "hello"

    monkeypatch.setattr(providers, "openai_stream", fake_stream)
    out = [x async for x in providers.stream("openai::gpt-4o", [{"role": "user", "content": "hi"}], None, None, None, False, 60)]
    assert out == ["hello"]
    s = spend_service.month_summary(providers.get("openai"))
    assert s["calls"] == 1 and s["all_reported"] and s["estimated_cost"] == pytest.approx(0.0075)
    # Next call: 0.0075 < 0.01 still allowed; after it, the limit is reached.
    [x async for x in providers.stream("openai::gpt-4o", [{"role": "user", "content": "hi"}], None, None, None, False, 60)]
    with pytest.raises(providers.ProviderBlocked, match="monthly limit"):
        [x async for x in providers.stream("openai::gpt-4o", [{"role": "user", "content": "hi"}], None, None, None, False, 60)]

    settings.update({"routing_policy": "local_only"})
    with pytest.raises(providers.ProviderBlocked, match="Local-only"):
        [x async for x in providers.stream("openai::gpt-4o", [], None, None, None, False, 60)]


async def test_estimates_when_not_reported(provs, monkeypatch):
    from app.services import spend_service

    async def fake_stream(p, model, msgs, images=None, options=None, fmt=None, emit_thinking=False, timeout=600, usage=None):
        yield "x" * 400

    monkeypatch.setattr(providers, "openai_stream", fake_stream)
    [x async for x in providers.stream("lms::qwen", [{"role": "user", "content": "y" * 80}], None, None, None, False, 60)]
    s = spend_service.month_summary(providers.get("lms"))
    assert s["calls"] == 1 and not s["all_reported"] and s["output_tokens"] == 100 and s["estimated_cost"] is None


def test_api_saves_controls_and_reports_usage(client, provs):
    r = client.post("/api/providers", json={"id": "groq", "base_url": "https://api.groq.com/openai/v1", "api_key": "k",
                                             "roles": ["small_fast"], "price_in": 0.05, "monthly_limit": 5}).json()
    assert r["roles"] == ["small_fast"] and r["price_in"] == 0.05 and r["monthly_limit"] == 5 and "api_key" not in r
    usage = {u["provider"]: u for u in client.get("/api/providers/usage").json()["usage"]}
    assert usage["groq"]["prices_set"] and usage["lms"]["prices_set"] is False
