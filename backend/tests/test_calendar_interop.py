"""Calendar .ics import/export round trip and conflict checks."""
from __future__ import annotations

from datetime import UTC, datetime

ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nUID:abc-1@example\r\nSUMMARY:Dentist\\, check-up\r\n"
    "DTSTART:20261201T093000Z\r\nDTEND:20261201T100000Z\r\n"
    "DESCRIPTION:Bring the form\\nand insurance card. This line is long enough to need fol\r\n ding by the exporter.\r\n"
    "LOCATION:Main St 4\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:abc-2@example\r\nSUMMARY:Holiday\r\nDTSTART;VALUE=DATE:20261224\r\nDTEND;VALUE=DATE:20261227\r\n"
    "RRULE:FREQ=YEARLY\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


def test_import_export_roundtrip(client):
    r = client.post("/api/calendar/import", json={"ics": ICS}).json()
    assert r == {"added": 2, "updated": 0}
    assert client.post("/api/calendar/import", json={"ics": ICS}).json() == {"added": 0, "updated": 2}
    ev = {e["title"]: e for e in client.get("/api/calendar/events").json()}
    d = ev["Dentist, check-up"]
    assert d["start_ts"] == datetime(2026, 12, 1, 9, 30, tzinfo=UTC).timestamp()
    assert "Bring the form\nand insurance card" in d["description"] and "folding" in d["description"]
    assert "Location: Main St 4" in d["description"]
    h = ev["Holiday"]
    assert h["all_day"] == 1 and "Repeats" in h["description"]
    assert datetime.fromtimestamp(h["end_ts"]).day == 26  # exclusive end handled

    out = client.get("/api/calendar/export.ics")
    assert out.headers["content-type"].startswith("text/calendar")
    text = out.text
    assert "UID:abc-1@example" in text and "SUMMARY:Dentist\\, check-up" in text
    assert "DTSTART;VALUE=DATE:20261224" in text and "DTEND;VALUE=DATE:20261227" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    # And it reads back the same.
    from app.services.calendar_service import parse_ics
    back = {e["title"]: e for e in parse_ics(text)}
    assert back["Dentist, check-up"]["start_ts"] == d["start_ts"]
    assert client.post("/api/calendar/import", json={"ics": "hello"}).status_code == 422


def test_conflict_check(client):
    base = datetime(2026, 12, 2, 14, 0).timestamp()
    assert client.post("/api/calendar/events", json={"title": "Call", "start_ts": base, "end_ts": base + 3600}).status_code == 200
    r = client.post("/api/calendar/events", json={"title": "Gym", "start_ts": base + 1800, "end_ts": base + 5400})
    assert r.status_code == 409 and r.json()["conflicts"][0]["title"] == "Call"
    assert client.post("/api/calendar/events", json={"title": "Gym", "start_ts": base + 1800, "force": True}).status_code == 200
    assert client.post("/api/calendar/events", json={"title": "Later", "start_ts": base + 3600 * 3}).status_code == 200
    assert client.post("/api/calendar/events", json={"title": "Birthday", "start_ts": base, "all_day": True}).status_code == 200
    assert len(client.get(f"/api/calendar/conflicts?start_ts={base}&end_ts={base + 600}").json()) == 1
