import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

function formatValue(v) {
  if (v === null || v === undefined) return String(v);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function formatTime(ts) {
  if (!ts) return "";
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return "";
  }
}

function HistoryRow({ entry, onRevert, reverting }) {
  return (
    <div className="health-row">
      <div className="health-row-main">
        <span className="health-row-label">{entry.key}</span>
      </div>
      <div className="health-row-detail">
        <span className="health-row-field">{formatValue(entry.old_value)}</span>
        <span className="health-row-field">→</span>
        <span className="health-row-field">{formatValue(entry.new_value)}</span>
        <span className="health-row-field">{formatTime(entry.changed_at)}</span>
      </div>
      <div style={{ marginTop: "var(--space-1)" }}>
        <button
          className="icon-btn"
          disabled={reverting === entry.id}
          onClick={() => onRevert(entry)}
          title="Revert to the previous value"
        >
          {reverting === entry.id ? "Reverting…" : "Revert"}
        </button>
      </div>
    </div>
  );
}

/** Standalone overlay panel showing the settings-change audit log (see
 * settings_history_service.py) — every config.settings.set() call, with
 * a one-click revert back to the prior value. Mirrors HealthPanel's
 * overlay/dialog structure and CSS classes. Not wired into App.jsx /
 * SettingsPanel.jsx yet — a later integration pass mounts this. */
export default function SettingsHistoryPanel({ onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reverting, setReverting] = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .getSettingsHistory()
      .then((res) => setData(res))
      .catch((err) => setError(err.message || "Failed to load settings history."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const handleRevert = async (entry) => {
    if (!window.confirm(`Revert "${entry.key}" back to ${formatValue(entry.old_value)}?`)) {
      return;
    }
    setReverting(entry.id);
    try {
      await api.revertSettingsHistory(entry.id);
      load();
    } catch (err) {
      setError(err.message || "Failed to revert.");
    } finally {
      setReverting(null);
    }
  };

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div
        className="calendar-modal"
        style={{ width: "min(560px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-history-panel-title"
      >
        <div className="calendar-header">
          <span id="settings-history-panel-title">Settings history</span>
          <div style={{ display: "flex", gap: "var(--space-1)" }}>
            <button className="icon-btn" onClick={load} title="Refresh" aria-label="Refresh">
              <Icon name="rotate-ccw" size={14} />
            </button>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
        <div style={{ padding: "var(--space-3) var(--space-4)", maxHeight: "75vh", overflowY: "auto" }}>
          {loading && !data && <p className="conversation-empty">Loading…</p>}
          {error && <p className="conversation-empty">{error}</p>}
          {data && data.length === 0 && (
            <p className="conversation-empty">No settings have been changed yet.</p>
          )}
          {data && data.length > 0 && (
            <div className="health-list">
              {data.map((entry) => (
                <HistoryRow key={entry.id} entry={entry} onRevert={handleRevert} reverting={reverting} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
