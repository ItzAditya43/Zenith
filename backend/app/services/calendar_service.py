"""Calendar interoperability: iCalendar (.ics) import and export, and
conflict checks before an event is created.

Uses a small standard-library reader/writer for the VEVENT parts other
calendars actually exchange (UID, SUMMARY, DESCRIPTION, DTSTART, DTEND,
all-day dates, folded lines, escaping) rather than a new dependency.
Imported events keep their UID, so importing the same file or a
calendar's secret iCal link again updates nothing twice. Recurring
events are imported as their first occurrence and say so in the notes.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import UTC, date, datetime, timedelta

from app.db.storage import _conn


def _unfold(text: str) -> list[str]:
    out: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _unescape(v: str) -> str:
    return re.sub(r"\\([\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _parse_dt(params: str, value: str) -> tuple[float, bool]:
    """(unix ts, all_day). UTC 'Z' values are exact; floating and TZID
    values are read as local time."""
    value = value.strip()
    if "VALUE=DATE" in params.upper() or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d.timestamp(), True
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).timestamp(), False
    return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").timestamp(), False


def parse_ics(text: str) -> list[dict]:
    events: list[dict] = []
    cur: dict | None = None
    for line in _unfold(text):
        if line.upper() == "BEGIN:VEVENT":
            cur = {}
            continue
        if line.upper() == "END:VEVENT":
            if cur and cur.get("start_ts") is not None:
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, _, params = head.partition(";")
        name = name.upper()
        try:
            if name == "UID":
                cur["uid"] = value.strip()
            elif name == "SUMMARY":
                cur["title"] = _unescape(value).strip()
            elif name == "DESCRIPTION":
                cur["description"] = _unescape(value).strip()
            elif name == "LOCATION":
                cur["location"] = _unescape(value).strip()
            elif name == "DTSTART":
                cur["start_ts"], cur["all_day"] = _parse_dt(params, value)
            elif name == "DTEND":
                cur["end_ts"], _ = _parse_dt(params, value)
            elif name == "RRULE":
                cur["recurring"] = True
        except ValueError:
            continue
    for e in events:
        e.setdefault("title", "(untitled)")
        notes = [e.get("description") or ""]
        if e.get("location"):
            notes.append(f"Location: {e['location']}")
        if e.get("recurring"):
            notes.append("(Repeats — imported as its first occurrence.)")
        e["description"] = "\n".join(n for n in notes if n).strip()
        if e.get("all_day") and e.get("end_ts"):
            e["end_ts"] -= 1  # DTEND for all-day events is exclusive
    return events


def import_ics(text: str) -> dict:
    added = updated = 0
    for e in parse_ics(text):
        uid = e.get("uid") or f"import-{uuid.uuid4().hex}"
        with _conn() as conn:
            row = conn.execute("SELECT id FROM calendar_events WHERE uid = ?", (uid,)).fetchone()
            if row:
                conn.execute("UPDATE calendar_events SET title = ?, description = ?, start_ts = ?, end_ts = ?, all_day = ? WHERE id = ?",
                             (e["title"], e["description"], e["start_ts"], e.get("end_ts"), 1 if e.get("all_day") else 0, row["id"]))
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO calendar_events (id, title, description, start_ts, end_ts, all_day, source_conversation_id, created_at, uid)"
                    " VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                    (str(uuid.uuid4()), e["title"], e["description"], e["start_ts"], e.get("end_ts"),
                     1 if e.get("all_day") else 0, time.time(), uid))
                added += 1
    return {"added": added, "updated": updated}


def export_ics() -> str:
    from app.db import storage

    def stamp(ts: float) -> str:
        return datetime.fromtimestamp(ts, UTC).strftime("%Y%m%dT%H%M%SZ")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Zenith//Calendar//EN", "CALSCALE:GREGORIAN"]
    for e in storage.list_calendar_events():
        lines += ["BEGIN:VEVENT", f"UID:{e.get('uid') or e['id'] + '@zenith'}", f"DTSTAMP:{stamp(e.get('created_at') or time.time())}"]
        if e.get("all_day"):
            d = date.fromtimestamp(e["start_ts"])
            end = date.fromtimestamp(e["end_ts"]) if e.get("end_ts") else d
            lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{end + timedelta(days=1):%Y%m%d}"]
        else:
            lines.append(f"DTSTART:{stamp(e['start_ts'])}")
            lines.append(f"DTEND:{stamp(e.get('end_ts') or e['start_ts'] + 3600)}")
        lines.append(f"SUMMARY:{_escape(e['title'])}")
        if e.get("description"):
            lines.append(f"DESCRIPTION:{_escape(e['description'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    folded = []
    for ln in lines:
        while len(ln.encode()) > 75:
            folded.append(ln[:73])
            ln = " " + ln[73:]
        folded.append(ln)
    return "\r\n".join(folded) + "\r\n"


def conflicts(start_ts: float, end_ts: float | None, all_day: bool = False, ignore_id: str | None = None) -> list[dict]:
    """Existing timed events that overlap [start, end). All-day events
    don't block timed ones (and vice versa) — they're usually reminders."""
    from app.db import storage

    end = end_ts if end_ts and end_ts > start_ts else start_ts + 3600
    out = []
    for e in storage.list_calendar_events(start_ts - 86400, end + 86400):
        if e["id"] == ignore_id or bool(e.get("all_day")) != bool(all_day):
            continue
        e_end = e.get("end_ts") or e["start_ts"] + 3600
        if e["start_ts"] < end and start_ts < e_end:
            out.append(e)
    return out
