import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

function fmt(ts) {
  return new Date(ts * 1000).toLocaleString(undefined, {
    weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/**
 * A plain local calendar — events stored in Zenith's own SQLite, no
 * Google/Outlook OAuth. Agenda-list view of the next 30 days, plus a quick
 * add form. Kept deliberately simple: this is a personal scheduling
 * surface, not a full calendar app.
 */
export default function CalendarPanel({ onClose }) {
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");

  const refresh = () => {
    const now = Date.now() / 1000;
    api
      .listCalendarEvents(now - 86400, now + 30 * 86400)
      .then((e) => {
        setEvents(e);
        setError(null);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(() => {
    refresh();
  }, []);

  const addEvent = async () => {
    if (!title.trim() || !when) return;
    const start_ts = new Date(when).getTime() / 1000;
    if (Number.isNaN(start_ts)) return;
    await api.createCalendarEvent({ title: title.trim(), start_ts });
    setTitle("");
    setWhen("");
    refresh();
  };

  const removeEvent = async (id) => {
    await api.deleteCalendarEvent(id);
    refresh();
  };

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div className="calendar-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="calendar-panel-title">
        <div className="calendar-header">
          <span id="calendar-panel-title">
            <Icon name="clock" size={14} /> Calendar
          </span>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        <div className="calendar-add-row">
          <input
            className="settings-input"
            placeholder="Event title"
            aria-label="Event title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <input
            className="settings-input"
            type="datetime-local"
            aria-label="Event date and time"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
          />
          <button className="settings-btn-primary" onClick={addEvent}>
            Add
          </button>
        </div>
        {error && <p className="settings-error">{error}</p>}
        <ul className="calendar-event-list">
          {events.map((e) => (
            <li key={e.id} className="calendar-event-item">
              <div>
                <div className="calendar-event-title">{e.title}</div>
                <div className="calendar-event-time">{fmt(e.start_ts)}</div>
              </div>
              <button className="icon-btn" onClick={() => removeEvent(e.id)} title="Delete" aria-label={`Delete ${e.title}`}>
                <Icon name="x" size={13} />
              </button>
            </li>
          ))}
          {events.length === 0 && !error && (
            <li className="conversation-empty">Nothing scheduled in the next 30 days.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
