"""Digest timing and provenance, notification dedupe, private-by-default push."""
from __future__ import annotations

import asyncio
import datetime as dt

import httpx


def test_digest_time_of_day(client):
    from app.core.config import settings
    from app.services import digest_service
    settings.update({"digest_time": "08:00"})
    try:
        today8 = dt.datetime.now().astimezone().replace(hour=8, minute=0, second=0, microsecond=0)
        before, after = today8.timestamp() - 60, today8.timestamp() + 60
        assert digest_service.is_due(None, before) is False
        assert digest_service.is_due(None, after) is True
        assert digest_service.is_due(after - 30, after + 3600) is False  # already ran today
        assert digest_service.is_due(today8.timestamp() - 86400 + 5, after) is True
    finally:
        settings.update({"digest_time": ""})


def test_digest_records_items(fake_ollama, monkeypatch):
    from app.db import storage
    from app.services import digest_service, memory_service
    memory_service.add_memory("prefers dark roast coffee")
    fake_ollama.final("You picked up one new fact.")
    d = asyncio.run(digest_service.run_now())
    assert d and any(i["kind"] == "memory" and i["why"] == "newly remembered" for i in d["items"])
    assert storage.latest_digest()["items"] == d["items"]


def test_notification_dedupe(client):
    from app.services import notification_service as ns
    a = ns.record("digest_generated", {"summary": "same"})
    b = ns.record("digest_generated", {"summary": "same"})
    assert b.get("duplicate") and b["id"] == a["id"]
    assert len(ns.list_notifications()) == 1


def test_push_is_private_by_default_and_test_endpoint(client, monkeypatch):
    from app.core.config import settings
    sent = []

    async def fake_post(self, url, content=None, headers=None, **kw):
        sent.append((url, content.decode(), headers))
        return httpx.Response(200)

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    settings.update({"notify_ntfy_enabled": True, "notify_ntfy_topic": "t0p1c", "notify_event_types": ["urgent_email"],
                     "notify_ntfy_url": "http://127.0.0.1:9"})
    from app.services import notify_service
    asyncio.run(notify_service.dispatch("urgent_email", {"subject": "Your bank statement", "summary": "secret stuff"}))
    assert "secret stuff" not in sent[-1][1] and "Open Zenith" in sent[-1][1]
    settings.update({"notify_ntfy_include_content": True})
    asyncio.run(notify_service.dispatch("urgent_email", {"subject": "Hi", "summary": "secret stuff"}))
    assert "secret stuff" in sent[-1][1] or "Hi" in sent[-1][1]
    r = client.post("/api/notifications/test").json()
    assert r["push"]["status"] == "sent" and r["in_app"]["event_type"] == "test"
    settings.update({"notify_ntfy_enabled": False, "notify_ntfy_include_content": False})
