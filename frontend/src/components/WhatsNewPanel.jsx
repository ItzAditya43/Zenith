import { CHANGELOG } from "../lib/changelog";
import Icon from "./Icon.jsx";

export default function WhatsNewPanel({ onClose }) {
  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div
        className="calendar-modal"
        style={{ width: "min(560px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="whats-new-title"
      >
        <div className="calendar-header">
          <span id="whats-new-title">
            <Icon name="bolt" size={14} /> What's new
          </span>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        <div style={{ maxHeight: "70vh", overflowY: "auto", padding: "0 var(--space-4) var(--space-4)" }}>
          {CHANGELOG.map((entry) => (
            <div key={entry.version} style={{ marginTop: "var(--space-4)" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-2)" }}>
                <h3 className="settings-section-title" style={{ margin: 0 }}>{entry.title}</h3>
                <span className="setting-hint">{entry.date}</span>
              </div>
              <ul style={{ margin: "var(--space-2) 0 0", paddingLeft: "1.2em" }}>
                {entry.items.map((item, i) => (
                  <li key={i} className="settings-section-desc" style={{ marginBottom: "var(--space-1)" }}>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
