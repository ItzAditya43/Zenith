"""Daily/weekly schedules in a timezone (DST-safe), missed runs, failure
pausing and soft delete."""
from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

from app.services import schedule_service as ss


def _ts(y, m, d, h, mi, tz="Europe/London"):
    return dt.datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz)).timestamp()


def test_daily_keeps_wall_clock_across_dst():
    s = {"kind": "daily", "time_of_day": "08:00", "timezone": "Europe/London", "interval_minutes": 1440}
    # Clocks go forward on 2026-03-29 in the UK.
    a = ss.next_run_after(s, _ts(2026, 3, 27, 9, 0))
    b = ss.next_run_after(s, a)
    for t in (a, b):
        local = dt.datetime.fromtimestamp(t, ZoneInfo("Europe/London"))
        assert (local.hour, local.minute) == (8, 0)
    assert b - a == 23 * 3600  # the short day


def test_weekly_picks_next_listed_weekday():
    s = {"kind": "weekly", "time_of_day": "18:30", "weekdays": "0,4", "timezone": "UTC", "interval_minutes": 1}
    # 2026-11-27 is a Friday (4); after 19:00 that day the next one is Monday.
    t = ss.next_run_after(s, _ts(2026, 11, 27, 19, 0, "UTC"))
    d = dt.datetime.fromtimestamp(t, ZoneInfo("UTC"))
    assert d.weekday() == 0 and (d.hour, d.minute) == (18, 30)


def test_missed_runs_counted_once():
    s = {"kind": "interval", "interval_minutes": 60, "next_run_at": 1000.0}
    assert ss.count_missed(s, 1000.0 + 3 * 3600 + 5) == 3
    assert ss.count_missed(s, 1001.0) == 0


def test_create_validates_and_soft_deletes(client):
    bad = client.post("/api/schedules", json={"name": "x", "prompt": "p", "kind": "daily", "time_of_day": "25:00"})
    assert bad.status_code == 400
    r = client.post("/api/schedules", json={"name": "Brief", "prompt": "p", "kind": "weekly", "time_of_day": "07:15",
                                            "weekdays": [1, 3], "timezone": "Asia/Kolkata"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert "Tue, Thu at 07:15" in s["description"] and s["next_run_at"]
    r2 = client.put(f"/api/schedules/{s['id']}/timing", json={"kind": "interval", "interval_minutes": 30})
    assert r2.json()["description"] == "Every 30 min"
    client.delete(f"/api/schedules/{s['id']}")
    assert client.get("/api/schedules").json() == []
    from app.db.storage import _conn
    with _conn() as conn:
        assert conn.execute("SELECT deleted_at FROM schedules WHERE id = ?", (s["id"],)).fetchone()[0]


def test_repeated_failures_notify_then_pause(client, monkeypatch):
    s = ss.create_schedule("Flaky", "p", "chat", 60)
    emitted = []

    async def boom(*a, **k):
        raise RuntimeError("model offline")

    async def fake_emit(kind, data):
        emitted.append((kind, data))

    monkeypatch.setattr(ss, "_ensure_conversation", boom)
    from app.services import events
    monkeypatch.setattr(events, "emit", fake_emit)
    for _ in range(ss.PAUSE_AFTER_FAILURES):
        asyncio.run(ss.run_schedule(ss.get_schedule(s["id"])))
    cur = ss.get_schedule(s["id"])
    assert cur["enabled"] == 0 and cur["consecutive_failures"] == ss.PAUSE_AFTER_FAILURES
    kinds = [k for k, _ in emitted]
    assert kinds.count("schedule_failing") == ss.PAUSE_AFTER_FAILURES - ss.NOTIFY_AFTER_FAILURES + 1
    assert emitted[-1][1]["paused"] is True
    client.patch(f"/api/schedules/{s['id']}", json={"enabled": True})
    assert ss.get_schedule(s["id"])["consecutive_failures"] == 0
