"""Notification history, per-event muting and quiet hours."""
from __future__ import annotations

from datetime import datetime


async def test_events_are_recorded_and_muting_controls_popups(client):
    from app.core.config import settings
    from app.services import events

    settings.update({"notify_desktop_muted": ["folder_file_added"], "notify_quiet_start": "", "notify_quiet_end": ""})
    try:
        await events.emit("schedule_completed", {"name": "Morning news", "result": "3 stories"})
        await events.emit("folder_file_added", {"folder": "~/Docs", "filename": "a.pdf"})
        r = client.get("/api/notifications").json()
        by = {n["event_type"]: n for n in r["items"]}
        assert r["unread"] == 2
        assert by["schedule_completed"]["desktop"] is True and by["schedule_completed"]["body"] == "3 stories"
        assert by["folder_file_added"]["desktop"] is False
        assert [n["event_type"] for n in client.get("/api/notifications?q=a.pdf").json()["items"]] == ["folder_file_added"]
        client.post("/api/notifications/read", json={"ids": [by["schedule_completed"]["id"]]})
        assert client.get("/api/notifications?unread=true").json()["unread"] == 1
        client.post("/api/notifications/read", json={})
        assert client.get("/api/notifications").json()["unread"] == 0
        assert client.delete("/api/notifications").json()["removed"] == 2
    finally:
        settings.update({"notify_desktop_muted": []})


def test_quiet_hours_wrap_midnight(temp_data_dir):
    from app.core.config import settings
    from app.services import notification_service as ns

    settings.update({"notify_quiet_start": "22:00", "notify_quiet_end": "07:00"})
    try:
        assert ns.in_quiet_hours(datetime(2026, 1, 1, 23, 30))
        assert ns.in_quiet_hours(datetime(2026, 1, 1, 6, 59))
        assert not ns.in_quiet_hours(datetime(2026, 1, 1, 12, 0))
        settings.update({"notify_quiet_start": "13:00", "notify_quiet_end": "14:00"})
        assert ns.in_quiet_hours(datetime(2026, 1, 1, 13, 30)) and not ns.in_quiet_hours(datetime(2026, 1, 1, 14, 0))
    finally:
        settings.update({"notify_quiet_start": "", "notify_quiet_end": ""})


def test_bad_quiet_hours_are_rejected(client):
    assert client.patch("/api/config", json={"notify_quiet_start": "25:00"}).status_code == 422
    assert client.patch("/api/config", json={"notify_quiet_start": "21:30"}).status_code == 200
