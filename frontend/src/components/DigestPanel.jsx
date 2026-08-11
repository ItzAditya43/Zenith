import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import { useEscapeToClose } from "../hooks/useEscapeToClose";

export default function DigestPanel({ onClose }) {
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);
  const [running, setRunning] = useState(false);
  useEscapeToClose(onClose);

  const refresh = () => api.getDigestHistory().then(setHistory).catch((err) => setError(err.message));

  useEffect(() => {
    refresh();
  }, []);

  const runNow = async () => {
    setRunning(true);
    setError(null);
    try {
      const result = await api.runDigestNow();
      if (!result.generated) {
        setError(result.reason || "Nothing new to summarize.");
      }
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div
        className="notes-modal"
        style={{ width: "min(560px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Daily digest"
      >
        <div className="notes-header">
          <span>Daily digest</span>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        <div className="settings-row" style={{ padding: "0.75rem 1rem" }}>
          <p className="settings-section-desc" style={{ margin: 0, flex: 1 }}>
            A short, unprompted summary of what changed in your watched folders and what's been
            learned about you recently. Enable the background version in Settings → Memory & persona.
          </p>
        </div>
        <div className="settings-row" style={{ padding: "0 1rem 0.75rem" }}>
          <button className="settings-btn-primary" onClick={runNow} disabled={running}>
            {running ? "Generating…" : "Generate now"}
          </button>
        </div>
        {error && <p className="settings-error" style={{ padding: "0 1rem" }}>{error}</p>}
        <ul className="calendar-event-list">
          {history.map((d) => (
            <li key={d.id} className="calendar-event-item" style={{ alignItems: "flex-start", flexDirection: "column" }}>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--text-tertiary)", marginBottom: "0.25rem" }}>
                {new Date(d.created_at * 1000).toLocaleString()} · {d.files_changed} file{d.files_changed === 1 ? "" : "s"}, {d.memories_added} new fact{d.memories_added === 1 ? "" : "s"}
              </div>
              <div style={{ fontSize: "var(--text-sm)", lineHeight: 1.6 }}>{d.content}</div>
            </li>
          ))}
          {history.length === 0 && !error && <p className="conversation-empty">No digests yet.</p>}
        </ul>
      </div>
    </div>
  );
}
